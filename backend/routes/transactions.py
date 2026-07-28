import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.deps import get_current_user
from db.models import LinkedAccount, Subscription, Transaction, User
from limiter import limiter
from services.job_queue import enqueue_item_sync
from services.subscription_sync import to_money
from services.transaction_store import get_user_transactions, serialize_transaction

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_linked_accounts(user: User, db: AsyncSession) -> list[LinkedAccount]:
    """Return the user's linked accounts, or 400 if none are connected."""
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == user.id)
    )
    accounts = list(result.scalars().all())
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="No bank account connected. Please connect your bank first."
        )
    return accounts


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


# Average charges per month for each billing frequency — the single source of
# truth for the dashboard's Monthly Spend and Annual Est. cards.
MONTHLY_FACTOR = {
    "weekly": 4.33,
    "biweekly": 2.17,
    "monthly": 1.0,
    "quarterly": 1 / 3,
    "yearly": 1 / 12,
}


async def _active_subscriptions_response(db: AsyncSession, user_id) -> dict:
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.is_active == True,  # noqa: E712
        )
    )
    serialized = [serialize_sub(s) for s in result.scalars().all()]
    # Monthly-equivalent spend across ALL frequencies, so a $120/year sub
    # shows as $10/month instead of being ignored.
    total_monthly = sum(
        s["amount"] * MONTHLY_FACTOR.get(s["frequency"], 1.0) for s in serialized
    )
    return {
        "subscriptions": serialized,
        "total_monthly_spend": round(total_monthly, 2),
        "annual_estimate": round(total_monthly * 12, 2),
        "count": len(serialized),
    }


@router.get("/transactions")
async def get_transactions(
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read stored transactions — kept fresh by webhooks and /subscriptions/sync."""
    await get_linked_accounts(current_user, db)
    try:
        rows = await get_user_transactions(db, current_user.id, days)
        return {
            "transactions": [serialize_transaction(r) for r in rows],
            "total": len(rows),
        }
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


@router.post("/subscriptions/sync", status_code=202)
@limiter.limit("10/minute")
async def sync_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kick off a durable sync for every linked account and return immediately.

    The actual Plaid pull + AI detection runs on the arq worker (the same job
    the webhook path uses) — doing that inline here, sequentially across every
    linked account, was slow enough to trip Cloudflare's edge timeout on
    accounts with a lot of history or more than one linked bank. The frontend
    polls GET /subscriptions/sync/status for completion.
    """
    accounts = await get_linked_accounts(current_user, db)
    accounts = [a for a in accounts if a.item_id]
    for account in accounts:
        account.sync_status = "syncing"
    await db.commit()
    for account in accounts:
        await enqueue_item_sync(account.item_id)
    return {"status": "syncing"}


@router.get("/subscriptions/sync/status")
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Poll target for the manual Sync button.

    Reports whether any linked account's durable sync job is still running,
    plus anything the user needs to act on once it finishes (a bank
    connection that needs reconnecting, or a job that failed).
    """
    accounts = await get_linked_accounts(current_user, db)
    response = await _active_subscriptions_response(db, current_user.id)
    response["syncing"] = any(a.sync_status == "syncing" for a in accounts)
    response["reconnect_needed"] = [
        a.institution_name or "Your bank" for a in accounts if a.status == "login_required"
    ]
    response["sync_error"] = any(a.sync_status == "error" for a in accounts)
    return response


@router.get("/summary")
async def get_spending_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Monthly spend over the stored transactions — a single DB query, no Plaid calls."""
    await get_linked_accounts(current_user, db)
    try:
        cutoff = date.today() - timedelta(days=180)
        result = await db.execute(
            select(Transaction.date, Transaction.amount).where(
                Transaction.user_id == current_user.id,
                Transaction.date >= cutoff,
                Transaction.amount > 0,  # positive = money out (Plaid convention)
            )
        )

        monthly: dict[str, float] = {}
        for txn_date, amount in result.all():
            month = txn_date.isoformat()[:7]
            monthly[month] = monthly.get(month, 0) + float(amount)

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
