import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from plaid_client import PLAID_ENV
from services.subscription_sync import sync_subscriptions_for_item
from services.webhook_verification import verify_plaid_webhook

router = APIRouter()
logger = logging.getLogger(__name__)

SYNC_TRIGGER_CODES = {"INITIAL_UPDATE", "HISTORICAL_UPDATE", "DEFAULT_UPDATE"}

TRANSACTIONS_CODES = SYNC_TRIGGER_CODES | {"TRANSACTIONS_REMOVED"}

ITEM_CODES = {
    "ERROR",
    "PENDING_EXPIRATION",
    "USER_PERMISSION_REVOKED",
    "WEBHOOK_UPDATE_ACKNOWLEDGED",
}


@router.post("/plaid")
async def plaid_webhook(request: Request, background_tasks: BackgroundTasks):
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
        return _handle_item(webhook_code, item_id, body.get("error"))

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


def _handle_item(code: str, item_id: str | None, error: dict | None) -> dict:
    if code == "ERROR":
        error_code = (error or {}).get("error_code", "UNKNOWN")
        logger.error("ITEM.ERROR for item %s: %s", item_id, error_code)
        return {
            "received": True,
            "webhook_type": "ITEM",
            "webhook_code": code,
            "error_code": error_code,
        }

    if code == "PENDING_EXPIRATION":
        logger.warning("ITEM.PENDING_EXPIRATION for item %s — token expiring", item_id)
    elif code == "USER_PERMISSION_REVOKED":
        logger.warning("ITEM.USER_PERMISSION_REVOKED for item %s", item_id)
    elif code == "WEBHOOK_UPDATE_ACKNOWLEDGED":
        logger.debug("ITEM.WEBHOOK_UPDATE_ACKNOWLEDGED for item %s", item_id)
    else:
        logger.debug("Unhandled ITEM code: %s", code)

    return {"received": True, "webhook_type": "ITEM", "webhook_code": code}
