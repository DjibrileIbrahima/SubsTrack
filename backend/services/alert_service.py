import logging
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Alert, Subscription, User
from services.email import send_alert_email

logger = logging.getLogger(__name__)


async def generate_upcoming_alerts(db: AsyncSession, days_ahead: int = 7) -> int:
    """Create Alert rows for subscriptions due within days_ahead days. Idempotent."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    result = await db.execute(
        select(Subscription).where(
            Subscription.is_active == True,
            Subscription.next_expected != None,
            Subscription.next_expected >= today,
            Subscription.next_expected <= cutoff,
        )
    )
    subs = result.scalars().all()

    # user_id -> list of dicts used both for Alert creation and email rendering
    new_by_user: dict = {}

    for sub in subs:
        existing = await db.execute(
            select(Alert).where(
                Alert.subscription_id == sub.id,
                Alert.due_date == sub.next_expected,
            )
        )
        if existing.scalar_one_or_none():
            continue

        days_until = (sub.next_expected - today).days
        if days_until == 0:
            when = "today"
        elif days_until == 1:
            when = "tomorrow"
        else:
            when = f"in {days_until} days"

        alert = Alert(
            user_id=sub.user_id,
            subscription_id=sub.id,
            message=f"{sub.merchant} renews {when} for ${sub.amount:.2f}",
            due_date=sub.next_expected,
        )
        db.add(alert)
        new_by_user.setdefault(sub.user_id, []).append(
            {"merchant": sub.merchant, "amount": sub.amount, "when": when}
        )

    total = sum(len(v) for v in new_by_user.values())

    if total:
        await db.commit()
        await _send_email_notifications(db, new_by_user)

    logger.info("Alert generation complete: %d new alerts created", total)
    return total


async def _send_email_notifications(db: AsyncSession, new_by_user: dict) -> None:
    if not new_by_user:
        return

    result = await db.execute(
        select(User).where(
            User.id.in_(list(new_by_user.keys())),
            User.alert_email == True,
        )
    )
    users = result.scalars().all()

    for user in users:
        alerts = new_by_user[user.id]
        await send_alert_email(user.email, alerts)
