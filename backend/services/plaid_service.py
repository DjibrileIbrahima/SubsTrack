"""Async wrappers around the synchronous Plaid SDK.

The plaid-python client is blocking, so every call is dispatched through
asyncio.to_thread to keep the event loop responsive. All Plaid API access
should go through this module rather than calling the client directly.
"""

import asyncio
import json
import os

from plaid.exceptions import ApiException
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from plaid_client import PLAID_COUNTRY_CODES, PLAID_PRODUCTS, client

_PAGE_SIZE = 500


def plaid_error_code(exc: ApiException) -> str:
    """Extract the error_code string from a Plaid ApiException body."""
    try:
        return json.loads(exc.body).get("error_code", "")
    except Exception:
        return ""


def plaid_error_code_from_exception(exc: BaseException) -> str | None:
    """Find a Plaid error_code in an exception or its causes, for structured
    logging (extra={"plaid_error_code": ...}) — the single most diagnostic
    string when a sync fails."""
    for candidate in (exc, exc.__cause__, exc.__context__):
        if isinstance(candidate, ApiException):
            return plaid_error_code(candidate) or None
    return None


def _sync_transactions_once(
    access_token: str, cursor: str | None
) -> tuple[list[dict], list[dict], list[dict], str | None]:
    added: list[dict] = []
    modified: list[dict] = []
    removed: list[dict] = []
    next_cursor = cursor
    has_more = True

    while has_more:
        kwargs: dict = {"access_token": access_token, "count": _PAGE_SIZE}
        if next_cursor:
            kwargs["cursor"] = next_cursor
        response = client.transactions_sync(TransactionsSyncRequest(**kwargs))
        added.extend(t.to_dict() for t in response["added"])
        modified.extend(t.to_dict() for t in response["modified"])
        removed.extend(r.to_dict() for r in response["removed"])
        has_more = response["has_more"]
        next_cursor = response["next_cursor"]

    return added, modified, removed, next_cursor


def _sync_transactions_blocking(
    access_token: str, cursor: str | None
) -> tuple[list[dict], list[dict], list[dict], str | None]:
    for attempt in range(2):
        try:
            return _sync_transactions_once(access_token, cursor)
        except ApiException as exc:
            code = plaid_error_code(exc)
            if code == "PRODUCT_NOT_READY":
                # Initial pull hasn't finished — a TRANSACTIONS webhook will
                # announce data later. Not an error; report nothing changed.
                return [], [], [], cursor
            if code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" and attempt == 0:
                # Item mutated mid-pagination — Plaid requires restarting from
                # the last committed cursor.
                continue
            raise
    raise RuntimeError("unreachable")


async def sync_transactions(
    access_token: str, cursor: str | None = None
) -> tuple[list[dict], list[dict], list[dict], str | None]:
    """Pull incremental transaction updates via Plaid /transactions/sync.

    Returns (added, modified, removed, next_cursor). Pass cursor=None for the
    first sync of an item; Plaid then returns its full history.
    """
    return await asyncio.to_thread(_sync_transactions_blocking, access_token, cursor)


async def create_link_token(user_id: str, access_token: str | None = None) -> str:
    """Create a Plaid Link token.

    Pass access_token to create an update-mode token (item re-authentication);
    update mode must not include products.
    """
    def _call() -> str:
        kwargs = {
            "client_name": "SubsTrack",
            "country_codes": PLAID_COUNTRY_CODES,
            "language": "en",
            "user": LinkTokenCreateRequestUser(client_user_id=user_id),
        }
        # Without this Plaid has nowhere to send ITEM/TRANSACTIONS webhooks and
        # account statuses never update. In update mode it also (re)registers
        # the webhook on the existing item.
        webhook_url = os.getenv("PLAID_WEBHOOK_URL")
        if webhook_url:
            kwargs["webhook"] = webhook_url
        if access_token:
            kwargs["access_token"] = access_token
        else:
            kwargs["products"] = PLAID_PRODUCTS
        response = client.link_token_create(LinkTokenCreateRequest(**kwargs))
        return response["link_token"]

    return await asyncio.to_thread(_call)


async def remove_item(access_token: str) -> None:
    """Revoke an access token at Plaid (severs the bank connection and stops
    item billing). An item that's already gone at Plaid counts as success —
    unlink must stay retryable after a partial failure.
    """
    def _call() -> None:
        try:
            client.item_remove(ItemRemoveRequest(access_token=access_token))
        except ApiException as exc:
            if plaid_error_code(exc) == "ITEM_NOT_FOUND":
                return
            raise

    await asyncio.to_thread(_call)


async def exchange_public_token(public_token: str) -> tuple[str, str | None]:
    """Exchange a public token for (access_token, item_id)."""
    def _call() -> tuple[str, str | None]:
        response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return response["access_token"], response.get("item_id")

    return await asyncio.to_thread(_call)
