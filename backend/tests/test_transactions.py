"""
Tests for /api/transactions, /api/subscriptions/*, and /api/summary routes.
"""

import uuid
import pytest
import pytest_asyncio
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from db.models import Subscription, LinkedAccount
from services.encryption import encrypt


# ─── Plaid mock factory ───────────────────────────────────────────────────────

def _make_plaid_txn(merchant="NETFLIX", amount=15.99, txn_date="2024-01-15"):
    """Return a mock Plaid transaction object."""
    mock = MagicMock()
    mock.to_dict.return_value = {
        "merchant_name": merchant,
        "name": merchant,
        "amount": amount,
        "date": txn_date,
        "category": ["Entertainment"],
    }
    return mock


def _plaid_get_response(*txns):
    resp = MagicMock()
    resp.__getitem__ = lambda self, k: list(txns) if k == "transactions" else None
    return resp


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

    async def test_unauthenticated(self, client):
        r = await client.post("/api/subscriptions/manual", json={
            "merchant": "Test", "amount": 5.00, "frequency": "monthly",
        })
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

    async def test_returns_plaid_transactions(self, auth_client, test_account):
        txn = _make_plaid_txn("SPOTIFY", 9.99, "2024-03-01")
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(txn)
            r = await auth_client.get("/api/transactions")

        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["transactions"][0]["merchant_name"] == "SPOTIFY"

    async def test_days_query_param(self, auth_client, test_account):
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response()
            r = await auth_client.get("/api/transactions?days=30")
        assert r.status_code == 200

    async def test_days_param_out_of_range(self, auth_client, test_account):
        r = await auth_client.get("/api/transactions?days=0")
        assert r.status_code == 422

        r = await auth_client.get("/api/transactions?days=400")
        assert r.status_code == 422

    async def test_plaid_error_returns_500(self, auth_client, test_account):
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.side_effect = Exception("Plaid timeout")
            r = await auth_client.get("/api/transactions")
        assert r.status_code == 500

    async def test_unauthenticated(self, client):
        r = await client.get("/api/transactions")
        assert r.status_code == 401


# ─── GET /api/subscriptions (sync) ───────────────────────────────────────────

class TestSyncSubscriptions:
    async def test_sync_detects_and_saves_subscriptions(self, auth_client, test_account, db, test_user):
        """Pipeline should detect Netflix as a subscription and persist it."""
        txns = [
            _make_plaid_txn("NETFLIX", 15.99, f"2024-0{m}-01")
            for m in range(1, 5)
        ]
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(*txns)
            r = await auth_client.get("/api/subscriptions")

        assert r.status_code == 200
        subs = r.json()["subscriptions"]
        assert any(s["merchant"] == "Netflix" for s in subs)

    async def test_sync_upserts_existing(self, auth_client, test_account, db, test_user):
        """Re-sync updates amount/frequency of existing plaid subscriptions."""
        existing = Subscription(
            user_id=test_user.id, merchant="Netflix",
            amount=10.00, frequency="monthly", source="plaid",
        )
        db.add(existing)
        await db.flush()

        txns = [_make_plaid_txn("NETFLIX", 15.99, f"2024-0{m}-01") for m in range(1, 5)]
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(*txns)
            r = await auth_client.get("/api/subscriptions")

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

        txns = [_make_plaid_txn("NETFLIX", 15.99, f"2024-0{m}-01") for m in range(1, 5)]
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(*txns)
            r = await auth_client.get("/api/subscriptions")

        assert r.status_code == 200
        subs = r.json()["subscriptions"]
        assert all(s["merchant"] != "Netflix" for s in subs)  # still hidden

    async def test_sync_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/subscriptions")
        assert r.status_code == 400

    async def test_sync_unauthenticated(self, client):
        r = await client.get("/api/subscriptions")
        assert r.status_code == 401


# ─── GET /api/summary ────────────────────────────────────────────────────────

class TestGetSummary:
    async def test_requires_bank_account(self, auth_client):
        r = await auth_client.get("/api/summary")
        assert r.status_code == 400

    async def test_groups_by_month(self, auth_client, test_account):
        txns = [
            _make_plaid_txn("NETFLIX", 15.99, "2024-01-15"),
            _make_plaid_txn("SPOTIFY", 9.99, "2024-01-20"),
            _make_plaid_txn("NETFLIX", 15.99, "2024-02-15"),
        ]
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(*txns)
            r = await auth_client.get("/api/summary")

        assert r.status_code == 200
        summary = r.json()["monthly_summary"]
        months = {s["month"] for s in summary}
        assert "2024-01" in months
        assert "2024-02" in months
        jan = next(s for s in summary if s["month"] == "2024-01")
        assert abs(jan["total"] - 25.98) < 0.01

    async def test_ignores_negative_amounts(self, auth_client, test_account):
        """Negative transactions (refunds) should be excluded from summary."""
        txns = [
            _make_plaid_txn("NETFLIX", 15.99, "2024-01-15"),
            _make_plaid_txn("REFUND", -5.00, "2024-01-20"),  # negative
        ]
        with patch("routes.transactions.client") as mock_plaid:
            mock_plaid.transactions_get.return_value = _plaid_get_response(*txns)
            r = await auth_client.get("/api/summary")

        assert r.status_code == 200
        jan = next((s for s in r.json()["monthly_summary"] if s["month"] == "2024-01"), None)
        assert jan is not None
        assert abs(jan["total"] - 15.99) < 0.01

    async def test_unauthenticated(self, client):
        r = await client.get("/api/summary")
        assert r.status_code == 401
