import logging
import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.deps import get_current_user
from db.models import LinkedAccount, Subscription, User
from limiter import limiter
from services.encryption import decrypt
from services.plaid_service import fetch_transactions
from services.subscription_sync import (
    detect_from_transactions,
    to_money,
    upsert_detected_subscriptions,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_access_tokens(user: User, db: AsyncSession) -> list[str]:
    """Fetch and decrypt the Plaid access tokens for every linked account."""
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == user.id)
    )
    accounts = result.scalars().all()
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="No bank account connected. Please connect your bank first."
        )
    return [decrypt(a.access_token) for a in accounts]


async def fetch_all_transactions(tokens: list[str], days: int) -> list[dict]:
    """Fetch and merge transactions across all linked accounts, newest first."""
    txns: list[dict] = []
    for token in tokens:
        txns.extend(await fetch_transactions(token, days))
    txns.sort(key=lambda t: t.get("date") or "", reverse=True)
    return txns


def serialize_sub(s) -> dict:
    """Serialize a Subscription model or dict to JSON-safe dict."""
    if isinstance(s, dict):
        return {
            **s,
            "amount": float(s["amount"]) if s.get("amount") is not None else None,
            "last_charged": s["last_charged"].isoformat() if isinstance(s.get("last_charged"), date) else s.get("last_charged"),
            "next_expected": s["next_expected"].isoformat() if isinstance(s.get("next_expected"), date) else s.get("next_expected"),
        }
    return {
        "id": str(s.id),
        "merchant": s.merchant,
        "amount": float(s.amount),
        "frequency": s.frequency,
        "category": s.category,
        "last_charged": s.last_charged.isoformat() if s.last_charged else None,
        "next_expected": s.next_expected.isoformat() if s.next_expected else None,
        "occurrences": s.occurrences,
        "source": s.source,
    }


async def _active_subscriptions_response(db: AsyncSession, user_id) -> dict:
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.is_active == True,  # noqa: E712
        )
    )
    serialized = [serialize_sub(s) for s in result.scalars().all()]
    total_monthly = sum(s["amount"] for s in serialized if s["frequency"] == "monthly")
    return {
        "subscriptions": serialized,
        "total_monthly_spend": round(total_monthly, 2),
        "count": len(serialized),
    }


@router.get("/transactions")
async def get_transactions(
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tokens = await get_access_tokens(current_user, db)
    try:
        txns = await fetch_all_transactions(tokens, days)
        return {"transactions": txns, "total": len(txns)}
    except Exception:
        logger.exception("Failed to fetch transactions")
        raise HTTPException(status_code=500, detail="Failed to fetch transactions")


@router.get("/subscriptions/saved")
async def get_saved_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all saved subscriptions from DB — no Plaid call."""
    try:
        return await _active_subscriptions_response(db, current_user.id)
    except Exception:
        logger.exception("Failed to fetch saved subscriptions")
        raise HTTPException(status_code=500, detail="Failed to fetch subscriptions")


@router.post("/subscriptions/sync")
@limiter.limit("10/minute")
async def sync_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync subscriptions from Plaid and update DB. POST because it writes."""
    tokens = await get_access_tokens(current_user, db)
    try:
        txns = await fetch_all_transactions(tokens, days=90)
        detected = await detect_from_transactions(txns)
        await upsert_detected_subscriptions(db, current_user.id, detected)
        return await _active_subscriptions_response(db, current_user.id)
    except Exception:
        await db.rollback()
        logger.exception("Failed to sync subscriptions")
        raise HTTPException(status_code=500, detail="Failed to sync subscriptions")


@router.get("/summary")
async def get_spending_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tokens = await get_access_tokens(current_user, db)
    try:
        txns = await fetch_all_transactions(tokens, days=180)

        monthly = {}
        for t in txns:
            amount = t.get("amount", 0)
            if not amount or amount <= 0:
                continue

            d = t["date"] if isinstance(t["date"], str) else t["date"].isoformat()
            month = d[:7]
            monthly[month] = monthly.get(month, 0) + amount

        summary = [{"month": k, "total": round(v, 2)} for k, v in sorted(monthly.items())]
        return {"monthly_summary": summary}
    except Exception:
        logger.exception("Failed to fetch spending summary")
        raise HTTPException(status_code=500, detail="Failed to fetch spending summary")


class ManualSubscriptionRequest(BaseModel):
    merchant: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0, le=100_000)
    frequency: Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"]
    next_expected: str | None = None
    category: str | None = Field(default="Manual", max_length=100)


@router.post("/subscriptions/manual")
@limiter.limit("30/minute")
async def add_manual_subscription(
    request: Request,
    body: ManualSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    next_expected = None
    if body.next_expected:
        try:
            next_expected = datetime.strptime(body.next_expected, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    # An inactive row for the same merchant still occupies the unique index slot,
    # so re-adding a previously deleted subscription must reactivate it instead.
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            func.lower(Subscription.merchant) == body.merchant.lower(),
            Subscription.source == "manual",
        )
    )
    existing = result.scalars().first()
    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail=f"You already have a subscription for {body.merchant}")

    try:
        if existing:
            existing.merchant = body.merchant
            existing.amount = to_money(body.amount)
            existing.frequency = body.frequency
            existing.next_expected = next_expected
            existing.category = body.category
            existing.is_active = True
            sub = existing
        else:
            sub = Subscription(
                user_id=current_user.id,
                merchant=body.merchant,
                amount=to_money(body.amount),
                frequency=body.frequency,
                next_expected=next_expected,
                category=body.category,
                source="manual",
            )
            db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return {"message": f"{body.merchant} added successfully", "subscription": serialize_sub(sub)}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a subscription for {body.merchant}")
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add manual subscription")


class UpdateSubscriptionRequest(BaseModel):
    merchant: str | None = Field(default=None, min_length=1, max_length=100)
    amount: float | None = Field(default=None, gt=0, le=100_000)
    frequency: Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"] | None = None
    next_expected: str | None = None
    category: str | None = Field(default=None, max_length=100)


@router.patch("/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: uuid.UUID,
    body: UpdateSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == current_user.id,
            Subscription.is_active == True,  # noqa: E712
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if body.merchant is not None:
        sub.merchant = body.merchant
    if body.amount is not None:
        sub.amount = to_money(body.amount)
    if body.frequency is not None:
        sub.frequency = body.frequency
    if body.next_expected is not None:
        try:
            sub.next_expected = datetime.strptime(body.next_expected, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    if body.category is not None:
        sub.category = body.category

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A subscription with that merchant already exists")
    await db.refresh(sub)
    return {"subscription": serialize_sub(sub)}


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.user_id == current_user.id,
                Subscription.is_active == True,  # noqa: E712
            )
        )
        sub = result.scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        sub.is_active = False
        await db.commit()
        return {"message": "Subscription removed"}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete subscriptions")
