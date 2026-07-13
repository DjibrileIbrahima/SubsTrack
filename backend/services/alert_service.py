import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Alert, Subscription, User
from services.email import send_alert_email

logger = logging.getLogger(__name__)


async def generate_upcoming_alerts(
    db: AsyncSession, days_ahead: int = 7, user_id=None
) -> int:
    """Create Alert rows for subscriptions due within days_ahead days. Idempotent.

    Pass user_id to scope to a single user (manual trigger from API).
    Omit user_id for the scheduled job which runs across all users.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    filters = [
        Subscription.is_active == True,  # noqa: E712
        Subscription.next_expected != None,  # noqa: E711
        Subscription.next_expected >= today,
        Subscription.next_expected <= cutoff,
    ]
    if user_id is not None:
        filters.append(Subscription.user_id == user_id)

    result = await db.execute(select(Subscription).where(*filters))
    subs = result.scalars().all()

    # One query for everything already alerted, instead of one per subscription
    already_alerted: set = set()
    if subs:
        pairs = await db.execute(
            select(Alert.subscription_id, Alert.due_date).where(
                Alert.subscription_id.in_([s.id for s in subs])
            )
        )
        already_alerted = set(pairs.all())

    # user_id -> list of dicts used both for Alert creation and email rendering
    new_by_user: dict = {}

    for sub in subs:
        if (sub.id, sub.next_expected) in already_alerted:
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
        try:
            # SAVEPOINT per insert: a concurrent run (cron + manual trigger)
            # racing the ix_alerts_subscription_due unique index just skips
            # the alert — and its email — instead of failing the whole job.
            async with db.begin_nested():
                db.add(alert)
        except IntegrityError:
            continue
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
            User.alert_email == True,  # noqa: E712
        )
    )
    users = result.scalars().all()

    for user in users:
        alerts = new_by_user[user.id]
        await send_alert_email(user.email, alerts)
