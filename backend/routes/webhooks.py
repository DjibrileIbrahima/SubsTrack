import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import LinkedAccount
from plaid_client import PLAID_ENV
from services.subscription_sync import sync_subscriptions_for_item
from services.webhook_verification import verify_plaid_webhook

router = APIRouter()
logger = logging.getLogger(__name__)

# All of these mean "new data is available via /transactions/sync" — including
# TRANSACTIONS_REMOVED, since the sync cursor also delivers removals.
SYNC_TRIGGER_CODES = {
    "SYNC_UPDATES_AVAILABLE",
    "INITIAL_UPDATE",
    "HISTORICAL_UPDATE",
    "DEFAULT_UPDATE",
    "TRANSACTIONS_REMOVED",
}

TRANSACTIONS_CODES = SYNC_TRIGGER_CODES

# ITEM webhook codes that map directly to a LinkedAccount.status value
ITEM_STATUS_BY_CODE = {
    "PENDING_EXPIRATION": "pending_expiration",
    "USER_PERMISSION_REVOKED": "revoked",
    "LOGIN_REPAIRED": "active",
}


@router.post("/plaid")
async def plaid_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()

    token = request.headers.get("Plaid-Verification")
    if token:
        try:
            await verify_plaid_webhook(token, raw_body)
        except ValueError as exc:
            logger.warning("Webhook signature verification failed: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    elif PLAID_ENV == "production":
        raise HTTPException(status_code=401, detail="Missing Plaid-Verification header")

    try:
        body = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    webhook_type = body.get("webhook_type", "").upper()
    webhook_code = body.get("webhook_code", "").upper()
    item_id = body.get("item_id")

    logger.info(
        "Plaid webhook received: type=%s code=%s item_id=%s",
        webhook_type, webhook_code, item_id,
    )

    if webhook_type == "TRANSACTIONS":
        return _handle_transactions(webhook_code, item_id, background_tasks)

    if webhook_type == "ITEM":
        return await _handle_item(webhook_code, item_id, body.get("error"), db)

    if webhook_type:
        logger.debug("Unhandled webhook type: %s", webhook_type)

    return {"received": True, "webhook_type": webhook_type, "webhook_code": webhook_code}


def _handle_transactions(code: str, item_id: str | None, background_tasks: BackgroundTasks) -> dict:
    if code not in TRANSACTIONS_CODES:
        logger.debug("Unhandled TRANSACTIONS code: %s", code)
        return {"received": True, "action": "ignored"}

    if code in SYNC_TRIGGER_CODES and item_id:
        background_tasks.add_task(sync_subscriptions_for_item, item_id)
        logger.info("TRANSACTIONS.%s for item %s — sync enqueued", code, item_id)
    else:
        logger.info("TRANSACTIONS.%s for item %s — acknowledged", code, item_id)

    return {
        "received": True,
        "webhook_type": "TRANSACTIONS",
        "webhook_code": code,
        "action": "acknowledged",
    }


async def _set_item_status(db: AsyncSession, item_id: str | None, status_value: str) -> None:
    if not item_id:
        return
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.item_id == item_id)
    )
    account = result.scalars().first()
    if account is None:
        logger.warning("ITEM webhook for unknown item_id=%s", item_id)
        return
    account.status = status_value
    await db.commit()
    logger.info("Linked account %s status set to %s", account.id, status_value)


async def _handle_item(code: str, item_id: str | None, error: dict | None, db: AsyncSession) -> dict:
    if code == "ERROR":
        error_code = (error or {}).get("error_code", "UNKNOWN")
        logger.error("ITEM.ERROR for item %s: %s", item_id, error_code)
        if error_code == "ITEM_LOGIN_REQUIRED":
            await _set_item_status(db, item_id, "login_required")
        return {
            "received": True,
            "webhook_type": "ITEM",
            "webhook_code": code,
            "error_code": error_code,
        }

    status_value = ITEM_STATUS_BY_CODE.get(code)
    if status_value:
        logger.warning("ITEM.%s for item %s — status set to %s", code, item_id, status_value)
        await _set_item_status(db, item_id, status_value)
    elif code == "WEBHOOK_UPDATE_ACKNOWLEDGED":
        logger.debug("ITEM.WEBHOOK_UPDATE_ACKNOWLEDGED for item %s", item_id)
    else:
        logger.debug("Unhandled ITEM code: %s", code)

    return {"received": True, "webhook_type": "ITEM", "webhook_code": code}
