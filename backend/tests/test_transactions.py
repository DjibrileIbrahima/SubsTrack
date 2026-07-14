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
    async def test_sync_detects_and_saves_subscriptions(self, auth_client, test_account, db, test_user):
        """Pipeline should detect Netflix as a subscription and persist it."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 200
        subs = r.json()["subscriptions"]
        assert any(s["merchant"] == "Netflix" for s in subs)

    async def test_sync_attributes_subscription_to_linked_account(
        self, auth_client, test_account, db, test_user
    ):
        """Detected subscriptions record which bank produced them (for scoped unlink)."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(added=_netflix_sync_txns())
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 200
        from sqlalchemy import select
        sub = (await db.execute(
            select(Subscription).where(Subscription.merchant == "Netflix")
        )).scalars().one()
        assert sub.linked_account_id == test_account.id

    async def test_sync_persists_transactions_and_cursor(self, auth_client, test_account, db, test_user):
        """Synced transactions land in the local table and the cursor is stored."""
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(
                added=_netflix_sync_txns(), cursor="cursor-after-sync",
            )
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 200
        from sqlalchemy import select
        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 3
        await db.refresh(test_account)
        assert test_account.sync_cursor == "cursor-after-sync"

    async def test_sync_paginates_until_has_more_is_false(self, auth_client, test_account, db):
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

        assert r.status_code == 200
        assert mock_plaid.transactions_sync.call_count == 2
        from sqlalchemy import select
        rows = (await db.execute(select(Transaction))).scalars().all()
        assert len(rows) == 2
        await db.refresh(test_account)
        assert test_account.sync_cursor == "cursor-end"

    async def test_sync_covers_all_linked_accounts(self, auth_client, test_account, db, test_user):
        """Every linked bank gets its own cursor sync."""
        from db.models import LinkedAccount
        from services.encryption import encrypt
        db.add(LinkedAccount(
            user_id=test_user.id,
            access_token=encrypt("access-sandbox-second-token"),
            item_id="item-sandbox-test-002",
            institution_name="Second Bank",
        ))
        await db.flush()

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = [
                _plaid_sync_response(added=[_make_plaid_txn("NETFLIX", 15.99, _days_ago(20), txn_id="txn-n1")]),
                _plaid_sync_response(added=[_make_plaid_txn("SPOTIFY", 9.99, _days_ago(20), txn_id="txn-sp1")]),
            ]
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 200
        assert mock_plaid.transactions_sync.call_count == 2
        from sqlalchemy import select
        merchants = {t.merchant_name for t in (await db.execute(select(Transaction))).scalars()}
        assert merchants == {"NETFLIX", "SPOTIFY"}

    async def test_sync_upserts_existing(self, auth_client, test_account, db, test_user):
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

        assert r.status_code == 200
        updated = next(s for s in r.json()["subscriptions"] if s["merchant"] == "Netflix")
        assert updated["amount"] == 15.99  # amount was updated

    async def test_sync_skips_inactive_subscriptions(self, auth_client, test_account, db, test_user):
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

        assert r.status_code == 200
        subs = r.json()["subscriptions"]
        assert all(s["merchant"] != "Netflix" for s in subs)  # still hidden

    async def test_sync_login_required_returns_409_and_marks_account(
        self, auth_client, test_account, db
    ):
        """A broken bank connection is a 409 naming the bank, not a 500 —
        and the account is flagged so Settings shows Reconnect."""
        import json as _json

        from plaid.exceptions import ApiException
        exc = ApiException(status=400, reason="bad request")
        exc.body = _json.dumps({"error_code": "ITEM_LOGIN_REQUIRED"})

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.transactions_sync.side_effect = exc
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "Test Bank" in detail
        assert "reconnect" in detail.lower()
        await db.refresh(test_account)
        assert test_account.status == "login_required"

    async def test_sync_requires_bank_account(self, auth_client):
        r = await auth_client.post("/api/subscriptions/sync")
        assert r.status_code == 400

    async def test_sync_unauthenticated(self, client):
        r = await client.post("/api/subscriptions/sync")
        assert r.status_code == 401


# ─── Subscription identity across price changes (merchant_key) ──────────────

class TestSubscriptionIdentity:
    async def test_price_change_updates_row_instead_of_duplicating(
        self, auth_client, test_account, db, test_user
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

        assert r.status_code == 200
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
        self, auth_client, test_account, db, test_user
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

        assert r.status_code == 200
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
        self, auth_client, test_account, db, test_user
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
            mock_plaid.transactions_sync.return_value = _plaid_sync_response(cursor="c2")
            r = await auth_client.post("/api/subscriptions/sync")

        assert r.status_code == 200
        from sqlalchemy import select
        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "spotify")
        )).scalars().all()
        assert len(rows) == 2
        assert {float(r.amount) for r in rows} == {9.99, 19.99}


# ─── GET /api/summary ────────────────────────────────────────────────────────

class TestGetSummary:
    async def test_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/summary")
        assert r.status_code == 400

    async def test_groups_by_month(self, auth_client, test_account, db, test_user):
        """Summary aggregates the stored transactions by month — no Plaid call."""
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

    async def test_ignores_negative_amounts(self, auth_client, test_account, db, test_user):
        """Negative transactions (refunds) should be excluded from summary."""
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
