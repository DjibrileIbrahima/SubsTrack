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

    async def test_resync_same_added_txn_is_idempotent(self, db, test_account):
        """Re-delivering the same 'added' transaction must not duplicate or error
        (the row already exists, so it takes the update path)."""
        added = [_plaid_txn("txn-1", amount=15.99)]
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = (added, [], [], "c1")
            await sync_account_transactions(db, test_account)
            mock_sync.return_value = ([_plaid_txn("txn-1", amount=16.99)], [], [], "c2")
            await sync_account_transactions(db, test_account)

        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 1
        assert float(rows[0].amount) == 16.99

    async def test_duplicate_insert_degrades_to_update(self, db, test_account):
        """If the same transaction id is already in the table but not seen by the
        upfront read (a concurrent insert), the SAVEPOINT path updates it instead
        of failing the sync."""
        added = [_plaid_txn("txn-dup", amount=12.00)]
        real_execute = db.execute
        call = {"n": 0}

        async def execute_hiding_first_read(statement, *args, **kwargs):
            # Insert the conflicting row right before the sync's first SELECT,
            # but make that SELECT return nothing so the code takes the insert path.
            text = str(statement).lower()
            if call["n"] == 0 and text.startswith("select") and "plaid_transaction_id" in text:
                call["n"] += 1
                db.add(Transaction(
                    plaid_transaction_id="txn-dup",
                    linked_account_id=test_account.id,
                    user_id=test_account.user_id,
                    amount=1, date=date.today(),
                ))
                await db.flush()
                empty = MagicMock()
                empty.scalars.return_value = []
                return empty
            return await real_execute(statement, *args, **kwargs)

        with (
            patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync,
            patch.object(db, "execute", side_effect=execute_hiding_first_read),
        ):
            mock_sync.return_value = (added, [], [], "c1")
            count = await sync_account_transactions(db, test_account)

        assert count == 1
        rows = (await db.execute(select(Transaction).where(
            Transaction.plaid_transaction_id == "txn-dup"))).scalars().all()
        assert len(rows) == 1
        assert float(rows[0].amount) == 12.00  # updated to the synced value

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


class TestItemLoginRequired:
    def _login_required_exc(self):
        from plaid.exceptions import ApiException
        exc = ApiException(status=400, reason="bad request")
        exc.body = json.dumps({"error_code": "ITEM_LOGIN_REQUIRED"})
        return exc

    async def test_marks_account_and_raises_domain_error(self, db, test_account):
        import pytest

        from services.transaction_store import ItemReauthRequired
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = self._login_required_exc()
            with pytest.raises(ItemReauthRequired) as excinfo:
                await sync_account_transactions(db, test_account)

        assert test_account.status == "login_required"
        assert "Test Bank" in str(excinfo.value)

    async def test_successful_sync_restores_active_status(self, db, test_account):
        """After the user reconnects, the next good sync self-heals the status
        even if the LOGIN_REPAIRED webhook never arrives."""
        test_account.status = "login_required"
        with patch(SYNC_PATH, new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = ([], [], [], "c1")
            await sync_account_transactions(db, test_account)

        assert test_account.status == "active"


class TestLinkTokenWebhookRegistration:
    def _link_response(self):
        resp = MagicMock()
        resp.__getitem__ = lambda self, k: "link-token" if k == "link_token" else None
        return resp

    async def test_webhook_url_included_when_configured(self):
        import os
        from unittest.mock import patch as env_patch

        from services import plaid_service
        with (
            patch("services.plaid_service.client") as mock_client,
            env_patch.dict(os.environ, {"PLAID_WEBHOOK_URL": "https://app.example.com/api/webhooks/plaid"}),
        ):
            mock_client.link_token_create.return_value = self._link_response()
            await plaid_service.create_link_token("user-1")

        request = mock_client.link_token_create.call_args[0][0]
        assert request.to_dict()["webhook"] == "https://app.example.com/api/webhooks/plaid"

    async def test_webhook_omitted_when_not_configured(self):
        import os
        from unittest.mock import patch as env_patch

        from services import plaid_service
        env = {k: v for k, v in os.environ.items() if k != "PLAID_WEBHOOK_URL"}
        with (
            patch("services.plaid_service.client") as mock_client,
            env_patch.dict(os.environ, env, clear=True),
        ):
            mock_client.link_token_create.return_value = self._link_response()
            await plaid_service.create_link_token("user-1")

        request = mock_client.link_token_create.call_args[0][0]
        assert "webhook" not in request.to_dict()


class TestRemoveItem:
    """plaid_service.remove_item — revocation at Plaid on unlink."""

    def _api_exception(self, error_code):
        from plaid.exceptions import ApiException
        exc = ApiException(status=400, reason="plaid error")
        exc.body = json.dumps({"error_code": error_code})
        return exc

    async def test_calls_item_remove(self):
        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            await plaid_service.remove_item("tok-123")
        mock_client.item_remove.assert_called_once()

    async def test_already_removed_item_is_success(self):
        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            mock_client.item_remove.side_effect = self._api_exception("ITEM_NOT_FOUND")
            await plaid_service.remove_item("tok-123")  # must not raise

    async def test_other_errors_propagate(self):
        import pytest
        from plaid.exceptions import ApiException

        from services import plaid_service
        with patch("services.plaid_service.client") as mock_client:
            mock_client.item_remove.side_effect = self._api_exception("INTERNAL_SERVER_ERROR")
            with pytest.raises(ApiException):
                await plaid_service.remove_item("tok-123")
