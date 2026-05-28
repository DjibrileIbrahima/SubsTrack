"""Background subscription sync triggered by Plaid webhooks."""

import logging
from datetime import date, timedelta

from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from sqlalchemy import select

from db.models import LinkedAccount, Subscription
from plaid_client import client as plaid_client
from services.encryption import decrypt
from services.subscription_pipeline import run_subscription_pipeline

logger = logging.getLogger(__name__)


async def sync_subscriptions_for_item(item_id: str) -> None:
    """Fetch fresh transactions from Plaid and upsert subscriptions for a linked account.

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

            access_token = decrypt(account.access_token)
            user_id = account.user_id

            end_date = date.today()
            start_date = end_date - timedelta(days=90)
            plaid_request = TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date,
                options=TransactionsGetRequestOptions(count=500),
            )
            response = plaid_client.transactions_get(plaid_request)
            txns = [t.to_dict() for t in response["transactions"]]
            for t in txns:
                if isinstance(t.get("date"), date):
                    t["date"] = t["date"].isoformat()

            detected = run_subscription_pipeline(txns)

            for sub in detected:
                existing_result = await db.execute(
                    select(Subscription).where(
                        Subscription.user_id == user_id,
                        Subscription.merchant == sub["merchant"],
                        Subscription.source == "plaid",
                    )
                )
                existing = existing_result.scalar_one_or_none()
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
                        user_id=user_id,
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
            logger.info(
                "Webhook sync complete for item_id=%s: %d subscriptions processed",
                item_id, len(detected),
            )

    except Exception:
        logger.exception("Webhook sync failed for item_id=%s", item_id)
