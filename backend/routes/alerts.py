import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from db.models import Alert, User
from db.deps import get_current_user
from services.alert_service import generate_upcoming_alerts
from limiter import limiter

router = APIRouter()
logger = logging.getLogger(__name__)


def serialize_alert(a: Alert) -> dict:
    return {
        "id": str(a.id),
        "subscription_id": str(a.subscription_id) if a.subscription_id else None,
        "message": a.message,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "is_read": a.is_read,
        "created_at": a.created_at.isoformat(),
    }


@router.get("/alerts")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == current_user.id)
        .order_by(Alert.is_read.asc(), Alert.created_at.desc())
    )
    alerts = result.scalars().all()
    return {
        "alerts": [serialize_alert(a) for a in alerts],
        "unread_count": sum(1 for a in alerts if not a.is_read),
    }


@router.patch("/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.user_id == current_user.id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    await db.commit()
    return serialize_alert(alert)


@router.delete("/alerts/{alert_id}")
async def delete_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.user_id == current_user.id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
    return {"message": "Alert deleted"}


@router.post("/alerts/generate")
@limiter.limit("5/minute")
async def trigger_alert_generation(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger alert generation scoped to the current user only."""
    try:
        count = await generate_upcoming_alerts(db, user_id=current_user.id)
        return {"message": f"{count} new alert(s) created"}
    except Exception:
        logger.exception("Failed to generate alerts")
        raise HTTPException(status_code=500, detail="Failed to generate alerts")
