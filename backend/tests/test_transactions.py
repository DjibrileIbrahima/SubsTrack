"""
Tests for /api/transactions, /api/subscriptions/*, and /api/summary routes.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from db.models import Subscription, Transaction

# ─── Plaid mock factory ───────────────────────────────────────────────────────

def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _make_plaid_txn(merchant="NETFLIX", amount=15.99, txn_date="2024-01-15", txn_id=None):
    """Return a mock Plaid transaction object (as delivered by /transactions/sync)."""
    mock = MagicMock()
    mock.to_dict.return_value = {
        "transaction_id": txn_id or f"txn-{merchant}-{txn_date}-{amount}",
        "merchant_name": merchant,
        "name": merchant,
        "amount": amount,
        "date": txn_date,
        "category": ["Entertainment"],
        "pending": False,
    }
    return mock


def _plaid_sync_response(added=(), modified=(), removed=(), has_more=False, cursor="cursor-1"):
    """Mock /transactions/sync response."""
    resp = MagicMock()
    data = {
        "added": list(added),
        "modified": list(modified),
        "removed": list(removed),
        "has_more": has_more,
        "next_cursor": cursor,
    }
    resp.__getitem__ = lambda self, k: data.get(k)
    return resp


def _make_txn_row(user_id, account_id, merchant="NETFLIX", amount=15.99, days_back=10):
    """Build a stored Transaction row for seeding the test DB."""
    return Transaction(
        user_id=user_id,
        linked_account_id=account_id,
        plaid_transaction_id=f"txn-{uuid.uuid4()}",
        amount=amount,
        date=date.today() - timedelta(days=days_back),
        name=merchant,
        merchant_name=merchant,
        category="Entertainment",
    )


# ─── GET /api/subscriptions/saved ────────────────────────────────────────────

class TestGetSavedSubscriptions:
    async def test_empty_list(self, auth_client):
        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        data = r.json()
        assert data["subscriptions"] == []
        assert data["count"] == 0
        assert data["total_monthly_spend"] == 0

    async def test_returns_own_subscriptions(self, auth_client, test_subscription):
        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        subs = r.json()["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["merchant"] == "Netflix"

    async def test_monthly_total_calculation(self, auth_client, db, test_user):
        db.add(Subscription(user_id=test_user.id, merchant="Netflix", amount=15.99,
                            frequency="monthly", source="manual"))
        db.add(Subscription(user_id=test_user.id, merchant="Spotify", amount=9.99,
                            frequency="monthly", source="manual"))
        await db.flush()

        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        assert abs(r.json()["total_monthly_spend"] - 25.98) < 0.01

    async def test_monthly_total_includes_all_frequencies_as_monthly_equivalent(
        self, auth_client, db, test_user
    ):
        """A $120/year and a $10/week sub must show real monthly spend, not $0."""
        db.add(Subscription(user_id=test_user.id, merchant="Yearly Service", amount=120.00,
                            frequency="yearly", source="manual"))
        db.add(Subscription(user_id=test_user.id, merchant="Weekly Service", amount=10.00,
                            frequency="weekly", source="manual"))
        await db.flush()

        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        body = r.json()
        # 120/12 + 10*4.33 = 10 + 43.30 = 53.30
        assert abs(body["total_monthly_spend"] - 53.30) < 0.01
        # annual estimate is the same monthly-equivalent number x 12
        assert abs(body["annual_estimate"] - 639.60) < 0.01

    async def test_excludes_inactive_subscriptions(self, auth_client, db, test_user):
        db.add(Subscription(user_id=test_user.id, merchant="Dead", amount=5.0,
                            frequency="monthly", source="manual", is_active=False))
        await db.flush()

        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        assert all(s["merchant"] != "Dead" for s in r.json()["subscriptions"])

    async def test_does_not_leak_other_users_data(self, auth_client, db, test_user2):
        db.add(Subscription(user_id=test_user2.id, merchant="HiddenService", amount=12.0,
                            frequency="monthly", source="plaid"))
        await db.flush()

        r = await auth_client.get("/api/subscriptions/saved")
        assert r.status_code == 200
        assert all(s["merchant"] != "HiddenService" for s in r.json()["subscriptions"])

    async def test_unauthenticated(self, client):
        r = await client.get("/api/subscriptions/saved")
        assert r.status_code == 401


# ─── POST /api/subscriptions/manual ──────────────────────────────────────────

class TestAddManualSubscription:
    async def test_add_success(self, auth_client, db, test_user):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Notion",
            "amount": 8.00,
            "frequency": "monthly",
            "next_expected": str(date.today() + timedelta(days=15)),
        })
        assert r.status_code == 200
        body = r.json()
        assert body["subscription"]["merchant"] == "Notion"
        assert body["subscription"]["source"] == "manual"

    async def test_add_without_next_expected(self, auth_client):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "GitHub",
            "amount": 4.00,
            "frequency": "monthly",
        })
        assert r.status_code == 200
        assert r.json()["subscription"]["next_expected"] is None

    async def test_all_frequency_values(self, auth_client):
        for freq in ("weekly", "biweekly", "monthly", "quarterly", "yearly"):
            r = await auth_client.post("/api/subscriptions/manual", json={
                "merchant": f"Service-{freq}",
                "amount": 5.00,
                "frequency": freq,
            })
            assert r.status_code == 200, f"Failed for frequency={freq}"

    async def test_invalid_frequency(self, auth_client):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Test",
            "amount": 5.00,
            "frequency": "daily",  # not a valid choice
        })
        assert r.status_code == 422

    async def test_empty_merchant_rejected(self, auth_client):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "",
            "amount": 5.00,
            "frequency": "monthly",
        })
        assert r.status_code == 422

    async def test_negative_amount_rejected(self, auth_client):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Test",
            "amount": -1.00,
            "frequency": "monthly",
        })
        assert r.status_code == 422

    async def test_zero_amount_rejected(self, auth_client):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Test",
            "amount": 0,
            "frequency": "monthly",
        })
        assert r.status_code == 422

    async def test_duplicate_merchant_returns_409(self, auth_client):
        payload = {"merchant": "Notion", "amount": 8.00, "frequency": "monthly"}
        r = await auth_client.post("/api/subscriptions/manual", json=payload)
        assert r.status_code == 200
        r = await auth_client.post("/api/subscriptions/manual", json=payload)
        assert r.status_code == 409

    async def test_readding_deleted_subscription_reactivates_it(self, auth_client, db, test_user):
        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Notion", "amount": 8.00, "frequency": "monthly",
        })
        sub_id = r.json()["subscription"]["id"]
        r = await auth_client.delete(f"/api/subscriptions/{sub_id}")
        assert r.status_code == 200

        r = await auth_client.post("/api/subscriptions/manual", json={
            "merchant": "Notion", "amount": 10.00, "frequency": "yearly",
        })
        assert r.status_code == 200
        body = r.json()["subscription"]
        assert body["id"] == sub_id  # same row, reactivated
        assert body["amount"] == 10.00
        assert body["frequency"] == "yearly"

    async def test_unauthenticated(self, client):
        r = await client.post("/api/subscriptions/manual", json={
            "merchant": "Test", "amount": 5.00, "frequency": "monthly",
        })
        assert r.status_code == 401


# ─── PATCH /api/subscriptions/{id} ───────────────────────────────────────────

class TestUpdateSubscription:
    async def test_update_merchant(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"merchant": "Disney+"},
        )
        assert r.status_code == 200
        assert r.json()["subscription"]["merchant"] == "Disney+"

    async def test_update_amount(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"amount": 19.99},
        )
        assert r.status_code == 200
        assert r.json()["subscription"]["amount"] == 19.99

    async def test_update_frequency(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"frequency": "yearly"},
        )
        assert r.status_code == 200
        assert r.json()["subscription"]["frequency"] == "yearly"

    async def test_update_next_expected(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"next_expected": "2026-01-01"},
        )
        assert r.status_code == 200
        assert r.json()["subscription"]["next_expected"] == "2026-01-01"

    async def test_update_category(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"category": "Software"},
        )
        assert r.status_code == 200
        assert r.json()["subscription"]["category"] == "Software"

    async def test_partial_update_leaves_other_fields_unchanged(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"amount": 99.99},
        )
        assert r.status_code == 200
        body = r.json()["subscription"]
        assert body["merchant"] == "Netflix"
        assert body["frequency"] == "monthly"

    async def test_changes_persist_in_db(self, auth_client, test_subscription, db):
        await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"merchant": "Hulu", "amount": 7.99},
        )
        await db.refresh(test_subscription)
        assert test_subscription.merchant == "Hulu"
        assert float(test_subscription.amount) == 7.99

    async def test_invalid_frequency_returns_422(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"frequency": "daily"},
        )
        assert r.status_code == 422

    async def test_invalid_date_format_returns_400(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"next_expected": "not-a-date"},
        )
        assert r.status_code == 400
        assert "date" in r.json()["detail"].lower()

    async def test_negative_amount_returns_422(self, auth_client, test_subscription):
        r = await auth_client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"amount": -5.00},
        )
        assert r.status_code == 422

    async def test_nonexistent_subscription_returns_404(self, auth_client):
        import uuid
        r = await auth_client.patch(
            f"/api/subscriptions/{uuid.uuid4()}",
            json={"merchant": "Ghost"},
        )
        assert r.status_code == 404

    async def test_cannot_update_another_users_subscription(self, auth_client, test_user2, db):
        other_sub = Subscription(
            user_id=test_user2.id, merchant="Hulu",
            amount=7.99, frequency="monthly", source="manual",
        )
        db.add(other_sub)
        await db.flush()

        r = await auth_client.patch(
            f"/api/subscriptions/{other_sub.id}",
            json={"merchant": "Hijacked"},
        )
        assert r.status_code == 404

    async def test_cannot_update_inactive_subscription(self, auth_client, test_user, db):
        inactive = Subscription(
            user_id=test_user.id, merchant="Cancelled",
            amount=9.99, frequency="monthly", source="manual", is_active=False,
        )
        db.add(inactive)
        await db.flush()

        r = await auth_client.patch(
            f"/api/subscriptions/{inactive.id}",
            json={"merchant": "Updated"},
        )
        assert r.status_code == 404

    async def test_unauthenticated_returns_401(self, client, test_subscription):
        r = await client.patch(
            f"/api/subscriptions/{test_subscription.id}",
            json={"merchant": "X"},
        )
        assert r.status_code == 401


# ─── DELETE /api/subscriptions/{id} ──────────────────────────────────────────

class TestDeleteSubscription:
    async def test_delete_success(self, auth_client, test_subscription, db):
        r = await auth_client.delete(f"/api/subscriptions/{test_subscription.id}")
        assert r.status_code == 200
        assert "removed" in r.json()["message"].lower()

        await db.refresh(test_subscription)
        assert test_subscription.is_active is False  # soft delete

    async def test_delete_nonexistent(self, auth_client):
        r = await auth_client.delete(f"/api/subscriptions/{uuid.uuid4()}")
        assert r.status_code == 404

    async def test_delete_already_deleted(self, auth_client, test_subscription, db):
        test_subscription.is_active = False
        await db.flush()

        r = await auth_client.delete(f"/api/subscriptions/{test_subscription.id}")
        assert r.status_code == 404

    async def test_delete_other_users_subscription(self, auth_client, db, test_user2):
        """Data isolation: cannot delete another user's subscription."""
        other_sub = Subscription(
            user_id=test_user2.id, merchant="Hulu", amount=7.99,
            frequency="monthly", source="plaid",
        )
        db.add(other_sub)
        await db.flush()

        r = await auth_client.delete(f"/api/subscriptions/{other_sub.id}")
        assert r.status_code == 404

    async def test_delete_unauthenticated(self, client, test_subscription):
        r = await client.delete(f"/api/subscriptions/{test_subscription.id}")
        assert r.status_code == 401


# ─── GET /api/transactions ────────────────────────────────────────────────────

class TestGetTransactions:
    async def test_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/transactions")
        assert r.status_code == 400
        assert "bank account" in r.json()["detail"].lower()

    async def test_returns_stored_transactions(self, auth_client, test_account, db, test_user):
        """Reads come from the local transactions table — no Plaid call."""
        db.add(_make_txn_row(test_user.id, test_account.id, "SPOTIFY", 9.99, days_back=5))
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            r = await auth_client.get("/api/transactions")

        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["transactions"][0]["merchant_name"] == "SPOTIFY"
        mock_plaid.transactions_sync.assert_not_called()

    async def test_days_query_param_filters_window(self, auth_client, test_account, db, test_user):
        db.add(_make_txn_row(test_user.id, test_account.id, "RECENT", 5.0, days_back=10))
        db.add(_make_txn_row(test_user.id, test_account.id, "OLD", 5.0, days_back=60))
        await db.flush()

        r = await auth_client.get("/api/transactions?days=30")
        assert r.status_code == 200
        merchants = {t["merchant_name"] for t in r.json()["transactions"]}
        assert merchants == {"RECENT"}

    async def test_days_param_out_of_range(self, auth_client, test_account):
        r = await auth_client.get("/api/transactions?days=0")
        assert r.status_code == 422

        r = await auth_client.get("/api/transactions?days=400")
        assert r.status_code == 422

    async def test_does_not_leak_other_users_transactions(
        self, auth_client, test_account, db, test_user, test_user2
    ):
        from db.models import LinkedAccount
        from services.encryption import encrypt
        other_account = LinkedAccount(
            user_id=test_user2.id,
            access_token=encrypt("access-sandbox-other-token"),
            item_id="item-sandbox-other",
            institution_name="Other Bank",
        )
        db.add(other_account)
        await db.flush()
        db.add(_make_txn_row(test_user2.id, other_account.id, "HIDDEN", 9.99, days_back=5))
        db.add(_make_txn_row(test_user.id, test_account.id, "MINE", 5.0, days_back=5))
        await db.flush()

        r = await auth_client.get("/api/transactions")
        assert r.status_code == 200
        merchants = {t["merchant_name"] for t in r.json()["transactions"]}
        assert merchants == {"MINE"}

    async def test_unauthenticated(self, client):
        r = await client.get("/api/transactions")
        assert r.status_code == 401


# ─── POST /api/subscriptions/sync ────────────────────────────────────────────

def _netflix_sync_txns():
    """Three monthly Netflix charges inside the 90-day detection window."""
    return [
        _make_plaid_txn("NETFLIX", 15.99, _days_ago(n), txn_id=f"txn-netflix-{n}")
        for n in (80, 50, 20)
    ]


class TestSyncSubscriptions:
    """POST enqueues a durable job per linked account and returns immediately
    (fixed a Cloudflare 524: doing the Plaid pull + AI detection inline could
    run past the edge timeout). `run_item_sync` simulates the arq worker
    picking up that job; GET /subscriptions/sync/status is how the frontend
    polls for the result."""

    async def test_sync_enqueues_and_marks_accounts_syncing(self, auth_client, test_account, db):
        r = await auth_client.post("/api/subscriptions/sync")
        assert r.status_code == 202
        assert r.json()["status"] == "syncing"
        await db.refresh(test_account)
        assert test_account.sync_status == "syncing"

    async def test_status_reports_syncing_until_job_runs(self, auth_client, test_account, run_item_sync):
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response()
            await auth_client.post("/api/subscriptions/sync")

            mid = await auth_client.get("/api/subscriptions/sync/status")
            assert mid.json()["syncing"] is True

            await run_item_sync(test_account.item_id)

        done = await auth_client.get("/api/subscriptions/sync/status")
        assert done.json()["syncing"] is False

    async def test_sync_detects_and_saves_subscriptions(self, auth_client, test_account, db, test_user, run_item_sync):
        """Pipeline should detect Netflix as a subscription and persist it."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        status = await auth_client.get("/api/subscriptions/sync/status")
        assert status.status_code == 200
        subs = status.json()["subscriptions"]
        assert any(s["merchant"] == "Netflix" for s in subs)

    async def test_sync_attributes_subscription_to_linked_account(
        self, auth_client, test_account, db, test_user, run_item_sync
    ):
        """Detected subscriptions record which bank produced them (for scoped unlink)."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        from sqlalchemy import select
        sub = (await db.execute(
            select(Subscription).where(Subscription.merchant == "Netflix")
        )).scalars().one()
        assert sub.linked_account_id == test_account.id

    async def test_sync_persists_transactions_and_cursor(self, auth_client, test_account, db, test_user, run_item_sync):
        """Synced transactions land in the local table and the cursor is stored."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(
                added=_netflix_sync_txns(), cursor="cursor-after-sync",
            )
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        from sqlalchemy import select
        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 3
        await db.refresh(test_account)
        assert test_account.sync_cursor == "cursor-after-sync"

    async def test_sync_paginates_until_has_more_is_false(self, auth_client, test_account, db, run_item_sync):
        page1 = _plaid_sync_response(
            added=[_make_plaid_txn("SPOTIFY", 9.99, _days_ago(40), txn_id="txn-s1")],
            has_more=True, cursor="cursor-mid",
        )
        page2 = _plaid_sync_response(
            added=[_make_plaid_txn("SPOTIFY", 9.99, _days_ago(10), txn_id="txn-s2")],
            has_more=False, cursor="cursor-end",
        )
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = [page1, page2]
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        assert mock_plaid.transactions_sync.call_count == 2
        from sqlalchemy import select
        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 2
        await db.refresh(test_account)
        assert test_account.sync_cursor == "cursor-end"

    async def test_sync_covers_all_linked_accounts(self, auth_client, test_account, db, test_user, run_item_sync):
        """Every linked bank gets its own cursor sync."""
        from db.models import LinkedAccount
        from services.encryption import encrypt
        second = LinkedAccount(
            user_id=test_user.id,
            access_token=encrypt("access-sandbox-second-token"),
            item_id="item-sandbox-test-002",
            institution_name="Second Bank",
        )
        db.add(second)
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = [
                _plaid_sync_response(added=[_make_plaid_txn("NETFLIX", 15.99, _days_ago(20), txn_id="txn-n1")]),
                _plaid_sync_response(added=[_make_plaid_txn("SPOTIFY", 9.99, _days_ago(20), txn_id="txn-sp1")]),
            ]
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)
            await run_item_sync(second.item_id)

        assert mock_plaid.transactions_sync.call_count == 2
        from sqlalchemy import select
        merchants = {t.merchant_name for t in (await db.execute(select(Transaction))).scalars()}
        assert merchants == {"NETFLIX", "SPOTIFY"}

    async def test_sync_upserts_existing(self, auth_client, test_account, db, test_user, run_item_sync):
        """Re-sync updates amount/frequency of existing plaid subscriptions."""
        existing = Subscription(
            user_id=test_user.id, merchant="Netflix",
            amount=10.00, frequency="monthly", source="plaid",
        )
        db.add(existing)
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        status = await auth_client.get("/api/subscriptions/sync/status")
        updated = next(s for s in status.json()["subscriptions"] if s["merchant"] == "Netflix")
        assert updated["amount"] == 15.99  # amount was updated

    async def test_sync_skips_inactive_subscriptions(self, auth_client, test_account, db, test_user, run_item_sync):
        """If a user manually deactivated a sub, sync should not re-activate it."""
        cancelled = Subscription(
            user_id=test_user.id, merchant="Netflix",
            amount=15.99, frequency="monthly", source="plaid", is_active=False,
        )
        db.add(cancelled)
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        status = await auth_client.get("/api/subscriptions/sync/status")
        subs = status.json()["subscriptions"]
        assert all(s["merchant"] != "Netflix" for s in subs)  # still hidden

    async def test_sync_login_required_marks_account_and_reports_reconnect(
        self, auth_client, test_account, db, run_item_sync
    ):
        """A broken bank connection doesn't crash the job — the account is
        flagged so Settings shows Reconnect, and the status poll names it."""
        import json as _json

        from plaid.exceptions import ApiException
        exc = ApiException(status=400, reason="bad request")
        exc.body = _json.dumps({"error_code": "ITEM_LOGIN_REQUIRED"})

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = exc
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        await db.refresh(test_account)
        assert test_account.status == "login_required"
        assert test_account.sync_status == "idle"

        status = await auth_client.get("/api/subscriptions/sync/status")
        assert status.status_code == 200
        body = status.json()
        assert body["syncing"] is False
        assert "Test Bank" in body["reconnect_needed"]

    async def test_sync_unexpected_failure_reported_as_sync_error(
        self, auth_client, test_account, db, run_item_sync
    ):
        """An unexpected exception in the job doesn't propagate — it's surfaced
        via the status poll instead of a 500 on the (already-returned) POST."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = RuntimeError("boom")
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        await db.refresh(test_account)
        assert test_account.sync_status == "error"

        status = await auth_client.get("/api/subscriptions/sync/status")
        assert status.json()["sync_error"] is True

    async def test_sync_requires_bank_account(self, auth_client):
        r = await auth_client.post("/api/subscriptions/sync")
        assert r.status_code == 400

    async def test_sync_unauthenticated(self, client):
        r = await client.post("/api/subscriptions/sync")
        assert r.status_code == 401


class TestSyncStatus:
    async def test_status_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/subscriptions/sync/status")
        assert r.status_code == 400

    async def test_status_unauthenticated(self, client):
        r = await client.get("/api/subscriptions/sync/status")
        assert r.status_code == 401

    async def test_status_idle_when_nothing_syncing(self, auth_client, test_account):
        r = await auth_client.get("/api/subscriptions/sync/status")
        assert r.status_code == 200
        body = r.json()
        assert body["syncing"] is False
        assert body["reconnect_needed"] == []
        assert body["sync_error"] is False


# ─── Subscription identity across price changes (merchant_key) ──────────────

class TestSubscriptionIdentity:
    async def test_price_change_updates_row_instead_of_duplicating(
        self, auth_client, test_account, db, test_user, run_item_sync
    ):
        """A legacy amount-labeled row must be matched by key when the price
        drifts, not duplicated by the new label."""
        stale = Subscription(
            user_id=test_user.id,
            linked_account_id=test_account.id,
            merchant="Netflix ($15.49)",
            merchant_key="netflix",
            amount=15.49,
            frequency="monthly",
            source="plaid",
        )
        db.add(stale)
        await db.flush()

        txns = [
            _make_plaid_txn("NETFLIX", 17.99, _days_ago(n), txn_id=f"txn-nfx-{n}")
            for n in (80, 50, 20)
        ]
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=txns)
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(
                Subscription.user_id == test_user.id,
                Subscription.merchant_key == "netflix",
            )
        )).scalars().all()
        assert len(rows) == 1  # updated in place, no duplicate
        assert rows[0].id == stale.id
        assert float(rows[0].amount) == 17.99
        assert rows[0].merchant == "Netflix"  # label refreshed

    async def test_distinct_plans_stay_separate_rows(
        self, auth_client, test_account, db, test_user, run_item_sync
    ):
        """Two price tiers of one merchant (beyond the match tolerance) must
        remain two subscriptions."""
        txns = [
            _make_plaid_txn("SPOTIFY", 9.99, _days_ago(n), txn_id=f"txn-sp-a-{n}")
            for n in (80, 50, 20)
        ] + [
            _make_plaid_txn("SPOTIFY", 19.99, _days_ago(n), txn_id=f"txn-sp-b-{n}")
            for n in (78, 48, 18)
        ]
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=txns)
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(
                Subscription.user_id == test_user.id,
                Subscription.merchant_key == "spotify",
            )
        )).scalars().all()
        assert len(rows) == 2
        assert {float(r.amount) for r in rows} == {9.99, 19.99}

    async def test_resync_of_two_plans_does_not_cross_match(
        self, auth_client, test_account, db, test_user, run_item_sync
    ):
        """Re-syncing the same two plans updates each row, never merges them."""
        txns = [
            _make_plaid_txn("SPOTIFY", 9.99, _days_ago(n), txn_id=f"txn-sp-a-{n}")
            for n in (80, 50, 20)
        ] + [
            _make_plaid_txn("SPOTIFY", 19.99, _days_ago(n), txn_id=f"txn-sp-b-{n}")
            for n in (78, 48, 18)
        ]
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=txns)
            await auth_client.post("/api/subscriptions/sync")
            await run_item_sync(test_account.item_id)

            mock_plaid.transactions_sync.return_value = _plaid_sync_response(cursor="c2")
            r = await auth_client.post("/api/subscriptions/sync")
            assert r.status_code == 202
            await run_item_sync(test_account.item_id)

        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "spotify")
        )).scalars().all()
        assert len(rows) == 2
        assert {float(r.amount) for r in rows} == {9.99, 19.99}


# ─── Display-label collisions (unique index is on the label) ────────────────

def _detection(merchant, key, amount):
    return {
        "merchant": merchant,
        "merchant_key": key,
        "amount": amount,
        "frequency": "monthly",
        "category": "Software",
        "last_charged": date.today() - timedelta(days=10),
        "next_expected": date.today() + timedelta(days=20),
        "occurrences": 3,
    }


class TestLabelCollisions:
    async def test_ai_collapsed_labels_do_not_violate_unique_index(self, db, test_user):
        """Regression: two price clusters whose labels the AI collapsed to the
        same plain name blew up the sync with UniqueViolationError (prod,
        2026-07-14, merchant 'tectra')."""
        from services.subscription_sync import upsert_detected_subscriptions
        db.add(Subscription(user_id=test_user.id, merchant="Tectra",
                            merchant_key="tectra", amount=4.99,
                            frequency="monthly", source="plaid"))
        db.add(Subscription(user_id=test_user.id, merchant="Tectra ($9.99)",
                            merchant_key="tectra", amount=9.99,
                            frequency="monthly", source="plaid"))
        await db.flush()

        detected = [
            _detection("Tectra", "tectra", 4.99),
            _detection("Tectra", "tectra", 9.99),  # AI collapsed the suffix
        ]
        await upsert_detected_subscriptions(db, test_user.id, detected)

        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "tectra")
        )).scalars().all()
        assert len(rows) == 2
        labels = {r.merchant.lower() for r in rows}
        assert len(labels) == 2  # labels stayed distinct
        assert {float(r.amount) for r in rows} == {4.99, 9.99}

    async def test_insert_gets_suffixed_label_when_plain_is_taken(self, db, test_user):
        """A new detection whose label is held by an unmatchable row is inserted
        under an amount-suffixed label instead of crashing."""
        from services.subscription_sync import upsert_detected_subscriptions
        db.add(Subscription(user_id=test_user.id, merchant="Tectra",
                            merchant_key="tectra", amount=4.99,
                            frequency="monthly", source="plaid"))
        await db.flush()

        detected = [
            _detection("Tectra", "tectra", 4.99),    # claims the existing row
            _detection("Tectra", "tectra", 50.00),   # beyond tolerance → insert
        ]
        await upsert_detected_subscriptions(db, test_user.id, detected)

        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "tectra")
        )).scalars().all()
        assert len(rows) == 2
        inserted = next(r for r in rows if float(r.amount) == 50.00)
        assert inserted.merchant == "Tectra ($50.00)"


# ─── GET /api/summary ────────────────────────────────────────────────────────

class TestGetSummary:
    async def test_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/summary")
        assert r.status_code == 400

    async def test_groups_by_month(self, auth_client, test_account, db, test_user):
        """Summary aggregates subscription-linked transactions by month — no Plaid call."""
        db.add(Subscription(user_id=test_user.id, merchant="Netflix", merchant_key="netflix",
                            amount=15.99, frequency="monthly", source="plaid"))
        db.add(Subscription(user_id=test_user.id, merchant="Spotify", merchant_key="spotify",
                            amount=9.99, frequency="monthly", source="plaid"))

        this_month = date.today().replace(day=15)
        prev_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=15)

        for merchant, amount, d in [
            ("NETFLIX", 15.99, prev_month),
            ("SPOTIFY", 9.99, prev_month),
            ("NETFLIX", 15.99, this_month),
        ]:
            row = _make_txn_row(test_user.id, test_account.id, merchant, amount)
            row.date = d
            db.add(row)
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            r = await auth_client.get("/api/summary")

        assert r.status_code == 200
        mock_plaid.transactions_sync.assert_not_called()
        summary = r.json()["monthly_summary"]
        months = {s["month"] for s in summary}
        assert prev_month.isoformat()[:7] in months
        assert this_month.isoformat()[:7] in months
        prev = next(s for s in summary if s["month"] == prev_month.isoformat()[:7])
        assert abs(prev["total"] - 25.98) < 0.01

    async def test_excludes_transactions_not_tied_to_a_subscription(
        self, auth_client, test_account, db, test_user
    ):
        """A one-off purchase (groceries, gas, ...) must not spike the chart —
        it's meant to track the same spend Monthly Spend/Annual Est. project."""
        db.add(Subscription(user_id=test_user.id, merchant="Netflix", merchant_key="netflix",
                            amount=15.99, frequency="monthly", source="plaid"))
        db.add(_make_txn_row(test_user.id, test_account.id, "NETFLIX", 15.99, days_back=10))
        db.add(_make_txn_row(test_user.id, test_account.id, "WHOLE FOODS", 120.00, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        month = (date.today() - timedelta(days=10)).isoformat()[:7]
        entry = next(s for s in r.json()["monthly_summary"] if s["month"] == month)
        assert abs(entry["total"] - 15.99) < 0.01  # groceries excluded

    async def test_no_active_subscriptions_yields_empty_summary(
        self, auth_client, test_account, db, test_user
    ):
        """No active subscriptions to attribute spend to → nothing to chart,
        even though raw transactions exist."""
        db.add(_make_txn_row(test_user.id, test_account.id, "NETFLIX", 15.99, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        assert r.json()["monthly_summary"] == []

    async def test_excludes_unrelated_purchase_sharing_a_broad_merchant_alias(
        self, auth_client, test_account, db, test_user
    ):
        """Merchant match alone isn't enough: normalize_merchant("APPLE") matches
        any Apple purchase, so a one-off hardware buy must still be excluded
        because its amount doesn't match the subscription's."""
        db.add(Subscription(user_id=test_user.id, merchant="Apple", merchant_key="apple",
                            amount=9.99, frequency="monthly", source="plaid"))
        db.add(_make_txn_row(test_user.id, test_account.id, "APPLE.COM/BILL", 9.99, days_back=10))
        db.add(_make_txn_row(test_user.id, test_account.id, "APPLE STORE", 1999.00, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        month = (date.today() - timedelta(days=10)).isoformat()[:7]
        entry = next(s for s in r.json()["monthly_summary"] if s["month"] == month)
        assert abs(entry["total"] - 9.99) < 0.01  # the MacBook purchase excluded

    async def test_excludes_stale_price_tier_sharing_a_merchant_key(
        self, auth_client, test_account, db, test_user
    ):
        """An old, now-cancelled price tier shares its merchant_key with a
        still-active tier — its historical charges must not count."""
        db.add(Subscription(user_id=test_user.id, merchant="Spotify", merchant_key="spotify",
                            amount=9.99, frequency="monthly", source="plaid"))
        db.add(Subscription(user_id=test_user.id, merchant="Spotify Family ($16.99)", merchant_key="spotify",
                            amount=16.99, frequency="monthly", source="plaid", is_active=False))
        db.add(_make_txn_row(test_user.id, test_account.id, "SPOTIFY", 9.99, days_back=10))
        db.add(_make_txn_row(test_user.id, test_account.id, "SPOTIFY", 16.99, days_back=40))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        totals = {s["month"]: s["total"] for s in r.json()["monthly_summary"]}
        recent_month = (date.today() - timedelta(days=10)).isoformat()[:7]
        older_month = (date.today() - timedelta(days=40)).isoformat()[:7]
        assert abs(totals.get(recent_month, 0) - 9.99) < 0.01
        assert older_month not in totals or totals[older_month] == 0  # stale tier excluded

    async def test_scopes_match_to_the_subscriptions_own_linked_account(
        self, auth_client, test_account, db, test_user
    ):
        """A similar-looking charge on a DIFFERENT linked account must not
        also count — only one account's history backs the active subscription,
        so counting every account with a matching merchant+amount multiplies
        the total by however many accounts happen to share that pattern."""
        from db.models import LinkedAccount
        from services.encryption import encrypt
        other_account = LinkedAccount(
            user_id=test_user.id,
            access_token=encrypt("access-sandbox-other-token"),
            item_id="item-sandbox-other",
            institution_name="Other Bank",
        )
        db.add(other_account)
        await db.flush()

        db.add(Subscription(user_id=test_user.id, merchant="Netflix", merchant_key="netflix",
                            amount=15.99, frequency="monthly", source="plaid",
                            linked_account_id=test_account.id))
        db.add(_make_txn_row(test_user.id, test_account.id, "NETFLIX", 15.99, days_back=10))
        db.add(_make_txn_row(test_user.id, other_account.id, "NETFLIX", 15.99, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        month = (date.today() - timedelta(days=10)).isoformat()[:7]
        entry = next(s for s in r.json()["monthly_summary"] if s["month"] == month)
        assert abs(entry["total"] - 15.99) < 0.01  # only test_account's charge counted

    async def test_legacy_subscription_without_linked_account_matches_any_account(
        self, auth_client, test_account, db, test_user
    ):
        """A subscription with no linked_account_id (manual, or a legacy
        pre-attribution row) can't be scoped to one account — fall back to
        matching on any account rather than dropping it entirely."""
        db.add(Subscription(user_id=test_user.id, merchant="Netflix", merchant_key="netflix",
                            amount=15.99, frequency="monthly", source="plaid",
                            linked_account_id=None))
        db.add(_make_txn_row(test_user.id, test_account.id, "NETFLIX", 15.99, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        month = (date.today() - timedelta(days=10)).isoformat()[:7]
        entry = next(s for s in r.json()["monthly_summary"] if s["month"] == month)
        assert abs(entry["total"] - 15.99) < 0.01

    async def test_ignores_negative_amounts(self, auth_client, test_account, db, test_user):
        """Negative transactions (refunds) should be excluded from summary."""
        db.add(Subscription(user_id=test_user.id, merchant="Netflix", merchant_key="netflix",
                            amount=15.99, frequency="monthly", source="plaid"))
        db.add(_make_txn_row(test_user.id, test_account.id, "NETFLIX", 15.99, days_back=10))
        db.add(_make_txn_row(test_user.id, test_account.id, "REFUND", -5.00, days_back=10))
        await db.flush()

        r = await auth_client.get("/api/summary")
        assert r.status_code == 200
        month = (date.today() - timedelta(days=10)).isoformat()[:7]
        entry = next((s for s in r.json()["monthly_summary"] if s["month"] == month), None)
        assert entry is not None
        assert abs(entry["total"] - 15.99) < 0.01

    async def test_unauthenticated(self, client):
        r = await client.get("/api/summary")
        assert r.status_code == 401
