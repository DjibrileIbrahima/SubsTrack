"""Tests for services/transaction_store.py and the plaid_service sync wrapper."""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from db.models import Transaction
from services.transaction_store import (
    get_user_transactions,
    sync_account_transactions,
    to_detection_dicts,
)

SYNC_PATH = "services.transaction_store.plaid_service.sync_transactions"


def _plaid_txn(txn_id, merchant="NETFLIX", amount=15.99, days_back=10, **extra):
    return {
        "transaction_id": txn_id,
        "merchant_name": merchant,
        "name": merchant,
        "amount": amount,
        "date": (date.today() - timedelta(days=days_back)).isoformat(),
        "category": ["Entertainment"],
        "pending": False,
        **extra,
    }


class TestSyncAccountTransactions:
    async def test_inserts_added_and_stores_cursor(self, db, test_account):
        added = [_plaid_txn("txn-1"), _plaid_txn("txn-2", "SPOTIFY", 9.99)]
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = (added, [], [], "cursor-new")
            count = await sync_account_transactions(db, test_account)

        assert count == 2
        rows = (await db.execute(select(Transaction))).scalars().all()
        assert {r.plaid_transaction_id for r in rows} == {"txn-1", "txn-2"}
        assert all(r.user_id == test_account.user_id for r in rows)
        assert test_account.sync_cursor == "cursor-new"

    async def test_passes_stored_cursor_to_plaid(self, db, test_account):
        test_account.sync_cursor = "cursor-old"
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([], [], [], "cursor-old")
            await sync_account_transactions(db, test_account)

        assert mock_sync.call_args[0][1] == "cursor-old"

    async def test_modified_updates_existing_row(self, db, test_account):
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([_plaid_txn("txn-1", amount=15.99)], [], [], "c1")
            await sync_account_transactions(db, test_account)
            mock_sync.return_value = ([], [_plaid_txn("txn-1", amount=17.99)], [], "c2")
            await sync_account_transactions(db, test_account)

        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 1
        assert float(rows[0].amount) == 17.99
        assert test_account.sync_cursor == "c2"

    async def test_removed_deletes_row(self, db, test_account):
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([_plaid_txn("txn-1"), _plaid_txn("txn-2")], [], [], "c1")
            await sync_account_transactions(db, test_account)
            mock_sync.return_value = ([], [], [{"transaction_id": "txn-1"}], "c2")
            await sync_account_transactions(db, test_account)

        rows = (await db.execute(select(Transaction))).scalars().all()
        assert [r.plaid_transaction_id for r in rows] == ["txn-2"]

    async def test_category_falls_back_to_personal_finance_category(self, db, test_account):
        txn = _plaid_txn("txn-1", category=None,
                         personal_finance_category={"primary": "GENERAL_SERVICES"})
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([txn], [], [], "c1")
            await sync_account_transactions(db, test_account)

        row = (await db.execute(select(Transaction))).scalars().one()
        assert row.category == "General Services"


class TestGetUserTransactions:
    async def test_window_filter_and_ordering(self, db, test_account, test_user):
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = (
                [_plaid_txn("t-old", days_back=120),
                 _plaid_txn("t-mid", days_back=40),
                 _plaid_txn("t-new", days_back=5)],
                [], [], "c1",
            )
            await sync_account_transactions(db, test_account)

        rows = await get_user_transactions(db, test_user.id, days=90)
        assert [r.plaid_transaction_id for r in rows] == ["t-new", "t-mid"]

    async def test_detection_dict_shape(self, db, test_account, test_user):
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([_plaid_txn("t-1", "SPOTIFY", 9.99, days_back=5)], [], [], "c1")
            await sync_account_transactions(db, test_account)

        rows = await get_user_transactions(db, test_user.id, days=90)
        dicts = to_detection_dicts(rows)
        assert dicts == [{
            "amount": 9.99,
            "date": (date.today() - timedelta(days=5)).isoformat(),
            "name": "SPOTIFY",
            "merchant_name": "SPOTIFY",
            "category": ["Entertainment"],
        }]


class TestPlaidSyncWrapper:
    """Error handling in plaid_service.sync_transactions."""

    def _api_exception(self, error_code):
        from plaid.exceptions import ApiException
        exc = ApiException(status=400, reason="plaid error")
        exc.body = json.dumps({"error_code": error_code})
        return exc

    def _sync_response(self, added=(), has_more=False, cursor="c-1"):
        resp = MagicMock()
        data = {
            "added": list(added), "modified": [], "removed": [],
            "has_more": has_more, "next_cursor": cursor,
        }
        resp.__getitem__ = lambda self, k: data.get(k)
        return resp

    async def test_product_not_ready_returns_empty(self):
        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            mock_client.transactions_sync.side_effect = self._api_exception("PRODUCT_NOT_READY")
            added, modified, removed, cursor = await plaid_service.sync_transactions("tok", None)

        assert (added, modified, removed) == ([], [], [])
        assert cursor is None  # original cursor preserved for the next attempt

    async def test_mutation_during_pagination_retries_once(self):
        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            mock_client.transactions_sync.side_effect = [
                self._api_exception("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"),
                self._sync_response(cursor="c-final"),
            ]
            added, modified, removed, cursor = await plaid_service.sync_transactions("tok", None)

        assert cursor == "c-final"
        assert mock_client.transactions_sync.call_count == 2

    async def test_other_plaid_errors_propagate(self):
        import pytest
        from plaid.exceptions import ApiException

        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            mock_client.transactions_sync.side_effect = self._api_exception("RATE_LIMIT_EXCEEDED")
            with pytest.raises(ApiException):
                await plaid_service.sync_transactions("tok", None)
