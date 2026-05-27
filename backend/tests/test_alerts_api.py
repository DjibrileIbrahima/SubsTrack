"""
Tests for /api/alerts routes.

Covers: list, generate, mark-read, delete, ordering, idempotency, cross-user isolation.
"""

import uuid
from datetime import date, timedelta

from db.models import Alert, Subscription

# ─── GET /api/alerts ─────────────────────────────────────────────────────────

class TestListAlerts:
    async def test_empty_list(self, auth_client):
        r = await auth_client.get("/api/alerts")
        assert r.status_code == 200
        data = r.json()
        assert data["alerts"] == []
        assert data["unread_count"] == 0

    async def test_returns_own_alerts(self, auth_client, db, test_user, test_subscription):
        alert = Alert(
            user_id=test_user.id,
            subscription_id=test_subscription.id,
            message="Netflix renews in 5 days for $15.99",
            due_date=date.today() + timedelta(days=5),
        )
        db.add(alert)
        await db.flush()

        r = await auth_client.get("/api/alerts")
        assert r.status_code == 200
        data = r.json()
        assert len(data["alerts"]) == 1
        assert data["unread_count"] == 1

    async def test_unread_count_accurate(self, auth_client, db, test_user, test_subscription):
        for i in range(3):
            db.add(Alert(
                user_id=test_user.id,
                message=f"Alert {i}",
                is_read=(i == 0),  # first one is already read
            ))
        await db.flush()

        r = await auth_client.get("/api/alerts")
        assert r.status_code == 200
        assert r.json()["unread_count"] == 2

    async def test_unread_alerts_returned_first(self, auth_client, db, test_user):
        """Ordering: unread before read, newest first within each group."""
        read_alert = Alert(user_id=test_user.id, message="Read alert", is_read=True)
        unread_alert = Alert(user_id=test_user.id, message="Unread alert", is_read=False)
        db.add(read_alert)
        db.add(unread_alert)
        await db.flush()

        r = await auth_client.get("/api/alerts")
        assert r.status_code == 200
        alerts = r.json()["alerts"]
        assert len(alerts) == 2
        assert alerts[0]["is_read"] is False  # unread comes first

    async def test_does_not_leak_other_users_alerts(self, auth_client, db, test_user2):
        other_alert = Alert(user_id=test_user2.id, message="Private alert")
        db.add(other_alert)
        await db.flush()

        r = await auth_client.get("/api/alerts")
        assert r.status_code == 200
        assert r.json()["alerts"] == []

    async def test_alert_payload_has_required_fields(self, auth_client, db, test_user):
        db.add(Alert(
            user_id=test_user.id,
            message="Test alert",
            due_date=date.today() + timedelta(days=3),
        ))
        await db.flush()

        r = await auth_client.get("/api/alerts")
        alert = r.json()["alerts"][0]
        required = {"id", "message", "due_date", "is_read", "created_at"}
        assert required.issubset(alert.keys())

    async def test_unauthenticated(self, client):
        r = await client.get("/api/alerts")
        assert r.status_code == 401


# ─── POST /api/alerts/generate ───────────────────────────────────────────────

class TestGenerateAlerts:
    async def test_generates_alert_for_upcoming_subscription(self, auth_client, db, test_user):
        sub = Subscription(
            user_id=test_user.id,
            merchant="Spotify",
            amount=9.99,
            frequency="monthly",
            next_expected=date.today() + timedelta(days=3),
            source="manual",
        )
        db.add(sub)
        await db.flush()

        r = await auth_client.post("/api/alerts/generate")
        assert r.status_code == 200
        assert "1" in r.json()["message"]

    async def test_generate_returns_zero_when_no_upcoming(self, auth_client, db, test_user):
        sub = Subscription(
            user_id=test_user.id,
            merchant="Annual",
            amount=99.0,
            frequency="yearly",
            next_expected=date.today() + timedelta(days=90),  # far in future
            source="manual",
        )
        db.add(sub)
        await db.flush()

        r = await auth_client.post("/api/alerts/generate")
        assert r.status_code == 200
        assert "0" in r.json()["message"]

    async def test_generate_is_idempotent(self, auth_client, db, test_user):
        sub = Subscription(
            user_id=test_user.id,
            merchant="Notion",
            amount=8.0,
            frequency="monthly",
            next_expected=date.today() + timedelta(days=2),
            source="manual",
        )
        db.add(sub)
        await db.flush()

        r1 = await auth_client.post("/api/alerts/generate")
        r2 = await auth_client.post("/api/alerts/generate")

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert "1" in r1.json()["message"]
        assert "0" in r2.json()["message"]  # second call creates 0 duplicates

    async def test_generate_scoped_to_current_user(self, auth_client, db, test_user2):
        """Generating alerts should only look at the current user's subscriptions."""
        other_sub = Subscription(
            user_id=test_user2.id,
            merchant="OtherService",
            amount=12.0,
            frequency="monthly",
            next_expected=date.today() + timedelta(days=1),
            source="manual",
        )
        db.add(other_sub)
        await db.flush()

        r = await auth_client.post("/api/alerts/generate")
        assert r.status_code == 200
        assert "0" in r.json()["message"]  # none for current user

    async def test_generate_unauthenticated(self, client):
        r = await client.post("/api/alerts/generate")
        assert r.status_code == 401


# ─── PATCH /api/alerts/{id}/read ─────────────────────────────────────────────

class TestMarkAlertRead:
    async def _create_alert(self, db, test_user):
        alert = Alert(user_id=test_user.id, message="Mark me read")
        db.add(alert)
        await db.flush()
        await db.refresh(alert)
        return alert

    async def test_mark_read_success(self, auth_client, db, test_user):
        alert = await self._create_alert(db, test_user)
        r = await auth_client.patch(f"/api/alerts/{alert.id}/read")
        assert r.status_code == 200
        assert r.json()["is_read"] is True

    async def test_mark_read_nonexistent_alert(self, auth_client):
        r = await auth_client.patch(f"/api/alerts/{uuid.uuid4()}/read")
        assert r.status_code == 404

    async def test_mark_read_other_users_alert(self, auth_client, db, test_user2):
        other_alert = Alert(user_id=test_user2.id, message="Private")
        db.add(other_alert)
        await db.flush()

        r = await auth_client.patch(f"/api/alerts/{other_alert.id}/read")
        assert r.status_code == 404

    async def test_mark_read_persists(self, auth_client, db, test_user):
        alert = await self._create_alert(db, test_user)
        await auth_client.patch(f"/api/alerts/{alert.id}/read")

        r = await auth_client.get("/api/alerts")
        alert_data = next(a for a in r.json()["alerts"] if str(alert.id) == a["id"])
        assert alert_data["is_read"] is True

    async def test_unauthenticated(self, client):
        r = await client.patch(f"/api/alerts/{uuid.uuid4()}/read")
        assert r.status_code == 401


# ─── DELETE /api/alerts/{id} ─────────────────────────────────────────────────

class TestDeleteAlert:
    async def _create_alert(self, db, test_user):
        alert = Alert(user_id=test_user.id, message="Delete me")
        db.add(alert)
        await db.flush()
        await db.refresh(alert)
        return alert

    async def test_delete_success(self, auth_client, db, test_user):
        alert = await self._create_alert(db, test_user)
        r = await auth_client.delete(f"/api/alerts/{alert.id}")
        assert r.status_code == 200
        assert "deleted" in r.json()["message"].lower()

    async def test_alert_gone_after_delete(self, auth_client, db, test_user):
        alert = await self._create_alert(db, test_user)
        await auth_client.delete(f"/api/alerts/{alert.id}")

        r = await auth_client.get("/api/alerts")
        ids = [a["id"] for a in r.json()["alerts"]]
        assert str(alert.id) not in ids

    async def test_delete_nonexistent(self, auth_client):
        r = await auth_client.delete(f"/api/alerts/{uuid.uuid4()}")
        assert r.status_code == 404

    async def test_delete_already_deleted(self, auth_client, db, test_user):
        alert = await self._create_alert(db, test_user)
        await auth_client.delete(f"/api/alerts/{alert.id}")

        r = await auth_client.delete(f"/api/alerts/{alert.id}")
        assert r.status_code == 404

    async def test_delete_other_users_alert(self, auth_client, db, test_user2):
        other_alert = Alert(user_id=test_user2.id, message="Private")
        db.add(other_alert)
        await db.flush()

        r = await auth_client.delete(f"/api/alerts/{other_alert.id}")
        assert r.status_code == 404

    async def test_unauthenticated(self, client):
        r = await client.delete(f"/api/alerts/{uuid.uuid4()}")
        assert r.status_code == 401
