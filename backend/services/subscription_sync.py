"""Subscription detection + upsert shared by the API route and Plaid webhooks."""

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LinkedAccount, Subscription
from services.groq_client import groq_model_call
from services.subscription_pipeline import run_subscription_pipeline
from services.transaction_store import (
    get_user_transactions,
    sync_account_transactions,
    to_detection_dicts,
)

logger = logging.getLogger(__name__)

# How far back detection looks when scoring recurring charges
DETECTION_WINDOW_DAYS = 90


def to_money(value) -> Decimal:
    """Coerce a detected/user-supplied amount to an exact 2-decimal value."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def detect_from_transactions(txns: list[dict]) -> list[dict]:
    """Run the detection pipeline off the event loop, falling back to rules-only."""
    try:
        return await asyncio.to_thread(run_subscription_pipeline, txns, groq_model_call)
    except Exception:
        logger.warning("AI pipeline failed — falling back to rules-only detection")
        return await asyncio.to_thread(run_subscription_pipeline, txns)


async def _find_existing(db: AsyncSession, user_id, merchant: str) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            func.lower(Subscription.merchant) == merchant.lower(),
            Subscription.source == "plaid",
        )
    )
    return result.scalars().first()


async def upsert_detected_subscriptions(db: AsyncSession, user_id, detected: list[dict]) -> None:
    """Upsert detected subscriptions and commit.

    Inserts run inside a SAVEPOINT so a concurrent sync (webhook + manual button)
    racing the ix_subscriptions_user_merchant_source unique index degrades to an
    update instead of failing the whole sync.
    """
    for sub in detected:
        existing = await _find_existing(db, user_id, sub["merchant"])
        if existing is None:
            try:
                async with db.begin_nested():
                    db.add(Subscription(
                        user_id=user_id,
                        merchant=sub["merchant"],
                        amount=to_money(sub["amount"]),
                        frequency=sub["frequency"],
                        category=sub["category"],
                        last_charged=sub["last_charged"],
                        next_expected=sub["next_expected"],
                        occurrences=sub["occurrences"],
                        source="plaid",
                    ))
                continue
            except IntegrityError:
                existing = await _find_existing(db, user_id, sub["merchant"])
                if existing is None:
                    raise

        if existing.is_active is False:
            continue  # user deactivated it — don't resurrect
        existing.merchant = sub["merchant"]
        existing.amount = to_money(sub["amount"])
        existing.frequency = sub["frequency"]
        existing.category = sub["category"]
        existing.last_charged = sub["last_charged"]
        existing.next_expected = sub["next_expected"]
        existing.occurrences = sub["occurrences"]

    await db.commit()


async def sync_subscriptions_for_item(item_id: str) -> None:
    """Pull incremental Plaid updates and upsert subscriptions for a linked account.

    Designed to run as a FastAPI BackgroundTask — creates its own DB session and
    swallows all exceptions so a failure never surfaces to the caller.
    """
    from db.database import AsyncSessionLocal  # local import avoids circular deps

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(LinkedAccount).where(LinkedAccount.item_id == item_id)
            )
            account = result.scalars().first()
            if not account:
                logger.warning("Webhook sync: no account found for item_id=%s", item_id)
                return

            await sync_account_transactions(db, account)
            rows = await get_user_transactions(db, account.user_id, DETECTION_WINDOW_DAYS)
            detected = await detect_from_transactions(to_detection_dicts(rows))
            await upsert_detected_subscriptions(db, account.user_id, detected)

            logger.info(
                "Webhook sync complete for item_id=%s: %d subscriptions processed",
                item_id, len(detected),
            )

    except Exception:
        logger.exception("Webhook sync failed for item_id=%s", item_id)
