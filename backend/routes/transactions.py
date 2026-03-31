import uuid
from fastapi import APIRouter, HTTPException, Depends
from datetime import date, timedelta, datetime
from typing import Optional, Literal
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid_client import client
from db.database import get_db
from db.models import LinkedAccount, Subscription, User
from db.deps import get_current_user
from services.subscription_pipeline import run_subscription_pipeline
from services.encryption import decrypt

router = APIRouter()


async def get_access_token(user: User, db: AsyncSession) -> str:
    """Fetch and decrypt the Plaid access token for a user."""
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == user.id)
    )
    account = result.scalars().first()
    if not account:
        raise HTTPException(
            status_code=400,
            detail="No bank account connected. Please connect your bank first."
        )
    return decrypt(account.access_token)


def serialize_sub(s) -> dict:
    """Serialize a Subscription model or dict to JSON-safe dict."""
    if isinstance(s, dict):
        return {
            **s,
            "last_charged": s["last_charged"].isoformat() if isinstance(s.get("last_charged"), date) else s.get("last_charged"),
            "next_expected": s["next_expected"].isoformat() if isinstance(s.get("next_expected"), date) else s.get("next_expected"),
        }
    return {
        "id": str(s.id),
        "merchant": s.merchant,
        "amount": s.amount,
        "frequency": s.frequency,
        "category": s.category,
        "last_charged": s.last_charged.isoformat() if s.last_charged else None,
        "next_expected": s.next_expected.isoformat() if s.next_expected else None,
        "occurrences": s.occurrences,
        "source": s.source,
        "confidence": getattr(s, "confidence", None),
        "detection_method": getattr(s, "detection_method", None),
        "reason": getattr(s, "reason", None),
    }


@router.get("/transactions")
async def get_transactions(
    days: int = 90,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await get_access_token(current_user, db)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        request = TransactionsGetRequest(
            access_token=token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=500),
        )
        response = client.transactions_get(request)
        txns = [t.to_dict() for t in response["transactions"]]
        for t in txns:
            if isinstance(t.get("date"), date):
                t["date"] = t["date"].isoformat()
        return {"transactions": txns, "total": len(txns)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions/saved")
async def get_saved_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all saved subscriptions from DB — no Plaid call."""
    try:
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == current_user.id,
                Subscription.is_active == True
            )
        )
        subs = result.scalars().all()
        serialized = [serialize_sub(s) for s in subs]
        total_monthly = sum(s["amount"] for s in serialized if s["frequency"] == "monthly")
        return {
            "subscriptions": serialized,
            "total_monthly_spend": round(total_monthly, 2),
            "count": len(serialized),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions")
async def sync_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync subscriptions from Plaid and update DB."""
    token = await get_access_token(current_user, db)
    end_date = date.today()
    start_date = end_date - timedelta(days=90)

    try:
        request = TransactionsGetRequest(
            access_token=token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=500),
        )
        response = client.transactions_get(request)
        txns = [t.to_dict() for t in response["transactions"]]
        for t in txns:
            if isinstance(t.get("date"), date):
                t["date"] = t["date"].isoformat()

        detected = run_subscription_pipeline(txns)

        for sub in detected:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == current_user.id,
                    Subscription.merchant == sub["merchant"],
                    Subscription.source == "plaid",
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                if existing.is_active is False:
                    continue
                existing.amount = sub["amount"]
                existing.frequency = sub["frequency"]
                existing.category = sub["category"]
                existing.last_charged = sub["last_charged"]
                existing.next_expected = sub["next_expected"]
                existing.occurrences = sub["occurrences"]
            else:
                db.add(Subscription(
                    user_id=current_user.id,
                    merchant=sub["merchant"],
                    amount=sub["amount"],
                    frequency=sub["frequency"],
                    category=sub["category"],
                    last_charged=sub["last_charged"],
                    next_expected=sub["next_expected"],
                    occurrences=sub["occurrences"],
                    source="plaid",
                ))

        await db.commit()

        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == current_user.id,
                Subscription.is_active == True,
            )
        )
        subs = result.scalars().all()

        serialized = [serialize_sub(s) for s in subs]
        total_monthly = sum(s["amount"] for s in serialized if s["frequency"] == "monthly")
        return {
            "subscriptions": serialized,
            "total_monthly_spend": round(total_monthly, 2),
            "count": len(serialized),
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_spending_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await get_access_token(current_user, db)
    end_date = date.today()
    start_date = end_date - timedelta(days=180)

    try:
        request = TransactionsGetRequest(
            access_token=token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=500),
        )
        response = client.transactions_get(request)
        txns = [t.to_dict() for t in response["transactions"]]

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ManualSubscriptionRequest(BaseModel):
    merchant: str
    amount: float
    frequency: Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"]
    next_expected: Optional[str] = None
    category: Optional[str] = "Manual"


@router.post("/subscriptions/manual")
async def add_manual_subscription(
    body: ManualSubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        next_expected = None
        if body.next_expected:
            next_expected = datetime.strptime(body.next_expected, "%Y-%m-%d").date()

        sub = Subscription(
            user_id=current_user.id,
            merchant=body.merchant,
            amount=body.amount,
            frequency=body.frequency,
            next_expected=next_expected,
            category=body.category,
            source="manual",
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return {"message": f"{body.merchant} added successfully", "subscription": serialize_sub(sub)}
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add manual subscription")


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
                Subscription.is_active == True,
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