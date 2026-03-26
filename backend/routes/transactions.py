from fastapi import APIRouter, HTTPException, Depends
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid_client import client
from db.database import get_db
from db.models import LinkedAccount, Subscription, User
from services.subscription_detector import detect_subscriptions
from services.encryption import decrypt

router = APIRouter()


async def get_access_token(user_id: str, db: AsyncSession) -> str:
    """Fetch and decrypt the stored Plaid access token for a user."""
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == user_id)
    )
    account = result.scalars().first()
    if not account:
        raise HTTPException(
            status_code=400,
            detail="No bank account connected. Please connect your bank first."
        )
    # Decrypt before use — never stored or logged in plaintext
    return decrypt(account.access_token)


@router.get("/transactions")
async def get_transactions(
    user_id: str = "default_user",
    days: int = 90,
    db: AsyncSession = Depends(get_db)
):
    """Fetch raw transactions for the last N days."""
    token = await get_access_token(user_id, db)
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


@router.get("/subscriptions")
async def get_subscriptions(
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db)
):
    """Detect subscriptions, persist to DB, and return results."""
    token = await get_access_token(user_id, db)
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

        detected = detect_subscriptions(txns)

        # Upsert subscriptions into DB
        for sub in detected:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.merchant == sub["merchant"]
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.amount = sub["amount"]
                existing.frequency = sub["frequency"]
                existing.last_charged = sub["last_charged"]
                existing.next_expected = sub["next_expected"]
                existing.occurrences = sub["occurrences"]
            else:
                db.add(Subscription(user_id=user_id, **sub))

        await db.commit()

        total_monthly = sum(s["amount"] for s in detected if s["frequency"] == "monthly")
        return {
            "subscriptions": detected,
            "total_monthly_spend": round(total_monthly, 2),
            "count": len(detected),
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_spending_summary(
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db)
):
    """Monthly spending breakdown for the last 6 months."""
    token = await get_access_token(user_id, db)
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
            d = t["date"] if isinstance(t["date"], str) else t["date"].isoformat()
            month = d[:7]
            monthly[month] = monthly.get(month, 0) + abs(t["amount"])

        summary = [{"month": k, "total": round(v, 2)} for k, v in sorted(monthly.items())]
        return {"monthly_summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Manual subscription routes ──

from pydantic import BaseModel
from typing import Optional

class ManualSubscriptionRequest(BaseModel):
    merchant: str
    amount: float
    frequency: str
    next_expected: Optional[str] = None
    category: Optional[str] = "Manual"


@router.post("/subscriptions/manual")
async def add_manual_subscription(
    body: ManualSubscriptionRequest,
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db)
):
    """Add a subscription manually (not from Plaid)."""
    try:
        # Ensure user exists
        result = await db.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(user_id=user_id)
            db.add(user)
            await db.flush()

        sub = Subscription(
            user_id=user_id,
            merchant=body.merchant,
            amount=body.amount,
            frequency=body.frequency,
            next_expected=body.next_expected,
            category=body.category,
            source="manual",
        )
        db.add(sub)
        await db.commit()
        return {"message": f"{body.merchant} added successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db)
):
    """Delete a subscription (manual only for safety)."""
    try:
        result = await db.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.user_id == user_id,
                Subscription.source == "manual"
            )
        )
        sub = result.scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        await db.delete(sub)
        await db.commit()
        return {"message": "Subscription deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
