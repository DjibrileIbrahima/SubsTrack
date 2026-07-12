"""Async wrappers around the synchronous Plaid SDK.

The plaid-python client is blocking, so every call is dispatched through
asyncio.to_thread to keep the event loop responsive. All Plaid API access
should go through this module rather than calling the client directly.
"""

import asyncio
from datetime import date, timedelta

from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from plaid_client import PLAID_COUNTRY_CODES, PLAID_PRODUCTS, client

_PAGE_SIZE = 500


def _fetch_transactions_sync(access_token: str, days: int) -> list[dict]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    txns: list[dict] = []
    while True:
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=_PAGE_SIZE, offset=len(txns)),
        )
        response = client.transactions_get(request)
        page = [t.to_dict() for t in response["transactions"]]
        txns.extend(page)

        total = response["total_transactions"]
        if not page or not isinstance(total, int) or len(txns) >= total:
            break

    for t in txns:
        if isinstance(t.get("date"), date):
            t["date"] = t["date"].isoformat()
    return txns


async def fetch_transactions(access_token: str, days: int = 90) -> list[dict]:
    """Fetch ALL transactions in the window, following pagination past 500 rows."""
    return await asyncio.to_thread(_fetch_transactions_sync, access_token, days)


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
        if access_token:
            kwargs["access_token"] = access_token
        else:
            kwargs["products"] = PLAID_PRODUCTS
        response = client.link_token_create(LinkTokenCreateRequest(**kwargs))
        return response["link_token"]

    return await asyncio.to_thread(_call)


async def exchange_public_token(public_token: str) -> tuple[str, str | None]:
    """Exchange a public token for (access_token, item_id)."""
    def _call() -> tuple[str, str | None]:
        response = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return response["access_token"], response.get("item_id")

    return await asyncio.to_thread(_call)
