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
    ItemReauthRequired,
    get_account_transactions,
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


# A detected charge matches an existing subscription when the amounts differ
# by no more than this (relative to the larger of the two). Wide enough to
# absorb price increases, narrow enough to keep distinct plans separate.
_AMOUNT_MATCH_TOLERANCE = 0.40


def _merchant_key(sub: dict) -> str:
    return (sub.get("merchant_key") or sub["merchant"]).lower()


def _amount_diff(a: float, b: float) -> float:
    top = max(abs(a), abs(b))
    return abs(a - b) / top if top else 0.0


async def _find_existing(
    db: AsyncSession, user_id, sub: dict, matched_ids: set
) -> Subscription | None:
    """Match a detection to an existing plaid subscription.

    Identity is merchant_key + closest amount within tolerance, so a price
    change updates the row instead of duplicating it. Falls back to an exact
    label match (pre-merchant_key rows, or a price jump past the tolerance
    on a single-plan merchant whose label is stable).
    """
    key = _merchant_key(sub)
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.source == "plaid",
            (Subscription.merchant_key == key)
            | (func.lower(Subscription.merchant) == sub["merchant"].lower()),
        )
    )
    rows = [r for r in result.scalars().all() if r.id not in matched_ids]
    if not rows:
        return None

    best = min(rows, key=lambda r: _amount_diff(float(r.amount), float(sub["amount"])))
    if _amount_diff(float(best.amount), float(sub["amount"])) <= _AMOUNT_MATCH_TOLERANCE:
        return best

    label = sub["merchant"].lower()
    return next((r for r in rows if r.merchant.lower() == label), None)


async def upsert_detected_subscriptions(
    db: AsyncSession, user_id, detected: list[dict], linked_account_id=None
) -> None:
    """Upsert detected subscriptions and commit.

    linked_account_id records which bank the detections came from, so that
    unlinking that bank only touches its own subscriptions.

    Inserts run inside a SAVEPOINT so a concurrent sync (webhook + manual button)
    racing the ix_subscriptions_user_merchant_source unique index degrades to an
    update instead of failing the whole sync.
    """
    matched_ids: set = set()
    for sub in detected:
        existing = await _find_existing(db, user_id, sub, matched_ids)
        if existing is None:
            try:
                new_row = Subscription(
                    user_id=user_id,
                    linked_account_id=linked_account_id,
                    merchant=sub["merchant"],
                    merchant_key=_merchant_key(sub),
                    amount=to_money(sub["amount"]),
                    frequency=sub["frequency"],
                    category=sub["category"],
                    last_charged=sub["last_charged"],
                    next_expected=sub["next_expected"],
                    occurrences=sub["occurrences"],
                    source="plaid",
                )
                async with db.begin_nested():
                    db.add(new_row)
                # claim the fresh row so a sibling cluster within tolerance
                # can't match (and overwrite) it later in this loop
                matched_ids.add(new_row.id)
                continue
            except IntegrityError:
                existing = await _find_existing(db, user_id, sub, matched_ids)
                if existing is None:
                    raise

        matched_ids.add(existing.id)  # one row per detection this round
        if existing.is_active is False:
            continue  # user deactivated it — don't resurrect
        if existing.linked_account_id is None and linked_account_id is not None:
            existing.linked_account_id = linked_account_id  # backfill legacy rows
        existing.merchant = sub["merchant"]
        existing.merchant_key = _merchant_key(sub)
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
            rows = await get_account_transactions(db, account.id, DETECTION_WINDOW_DAYS)
            detected = await detect_from_transactions(to_detection_dicts(rows))
            await upsert_detected_subscriptions(
                db, account.user_id, detected, linked_account_id=account.id
            )

            logger.info(
                "Webhook sync complete for item_id=%s: %d subscriptions processed",
                item_id, len(detected),
            )

    except ItemReauthRequired:
        # Expected state, not a bug: account already marked login_required so
        # the UI surfaces the Reconnect flow. No stack trace needed.
        logger.warning("Webhook sync: item %s needs re-authentication", item_id)
    except Exception:
        logger.exception("Webhook sync failed for item_id=%s", item_id)
