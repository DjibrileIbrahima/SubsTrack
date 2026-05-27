"""
Unit tests for services/alert_service.py

Tests the core alert generation logic (message text, idempotency, user scoping,
and email notification) using an in-memory DB, without going through HTTP.
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from db.models import Alert, Subscription, User
from services.alert_service import generate_upcoming_alerts


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _make_sub(db, user_id, merchant, amount, days_from_today, is_active=True):
    sub = Subscription(
        user_id=user_id,
        merchant=merchant,
        amount=amount,
        frequency="monthly",
        next_expected=date.today() + timedelta(days=days_from_today),
        source="manual",
        is_active=is_active,
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    return sub


# ─── Message wording ──────────────────────────────────────────────────────────

class TestAlertMessages:
    async def test_due_today_says_today(self, db, test_user):
        await _make_sub(db, test_user.id, "Netflix", 15.99, 0)
        count = await generate_upcoming_alerts(db, user_id=test_user.id)
        assert count == 1

        from sqlalchemy import select
        result = await db.execute(select(Alert).where(Alert.user_id == test_user.id))
        alert = result.scalar_one()
        assert "today" in alert.message.lower()
        assert "Netflix" in alert.message
        assert "15.99" in alert.message

    async def test_due_tomorrow_says_tomorrow(self, db, test_user):
        await _make_sub(db, test_user.id, "Spotify", 9.99, 1)
        await generate_upcoming_alerts(db, user_id=test_user.id)

        from sqlalchemy import select
        result = await db.execute(select(Alert).where(Alert.user_id == test_user.id))
        alert = result.scalar_one()
        assert "tomorrow" in alert.message.lower()

    async def test_due_in_n_days_says_in_n_days(self, db, test_user):
        await _make_sub(db, test_user.id, "GitHub", 4.0, 5)
        await generate_upcoming_alerts(db, user_id=test_user.id)

        from sqlalchemy import select
        result = await db.execute(select(Alert).where(Alert.user_id == test_user.id))
        alert = result.scalar_one()
        assert "in 5 days" in alert.message.lower()


# ─── Idempotency ─────────────────────────────────────────────────────────────

class TestIdempotency:
    async def test_second_run_creates_zero_alerts(self, db, test_user):
        await _make_sub(db, test_user.id, "Notion", 8.0, 3)

        count1 = await generate_upcoming_alerts(db, user_id=test_user.id)
        count2 = await generate_upcoming_alerts(db, user_id=test_user.id)

        assert count1 == 1
        assert count2 == 0

    async def test_multiple_subs_idempotent(self, db, test_user):
        await _make_sub(db, test_user.id, "Netflix", 15.99, 2)
        await _make_sub(db, test_user.id, "Spotify", 9.99, 4)

        first = await generate_upcoming_alerts(db, user_id=test_user.id)
        second = await generate_upcoming_alerts(db, user_id=test_user.id)

        assert first == 2
        assert second == 0


# ─── Filtering ────────────────────────────────────────────────────────────────

class TestFiltering:
    async def test_ignores_inactive_subscriptions(self, db, test_user):
        await _make_sub(db, test_user.id, "Dead", 5.0, 3, is_active=False)
        count = await generate_upcoming_alerts(db, user_id=test_user.id)
        assert count == 0

    async def test_ignores_far_future_subscriptions(self, db, test_user):
        await _make_sub(db, test_user.id, "Annual", 99.0, 30)  # >7 days default
        count = await generate_upcoming_alerts(db, user_id=test_user.id)
        assert count == 0

    async def test_custom_days_ahead_window(self, db, test_user):
        await _make_sub(db, test_user.id, "Quarterly", 30.0, 10)
        count = await generate_upcoming_alerts(db, days_ahead=14, user_id=test_user.id)
        assert count == 1

    async def test_subscription_without_next_expected_is_skipped(self, db, test_user):
        sub = Subscription(
            user_id=test_user.id, merchant="NoDate",
            amount=5.0, frequency="monthly", source="manual",
        )
        db.add(sub)
        await db.flush()

        count = await generate_upcoming_alerts(db, user_id=test_user.id)
        assert count == 0


# ─── User scoping ─────────────────────────────────────────────────────────────

class TestUserScoping:
    async def test_scoped_to_user_id(self, db, test_user, test_user2):
        await _make_sub(db, test_user.id, "UserOneSub", 5.0, 3)
        await _make_sub(db, test_user2.id, "UserTwoSub", 5.0, 3)

        count = await generate_upcoming_alerts(db, user_id=test_user.id)
        assert count == 1  # only user1's subscription

    async def test_global_run_covers_all_users(self, db, test_user, test_user2):
        await _make_sub(db, test_user.id, "Sub1", 5.0, 3)
        await _make_sub(db, test_user2.id, "Sub2", 5.0, 3)

        count = await generate_upcoming_alerts(db)  # no user_id = global
        assert count == 2


# ─── Email notification ───────────────────────────────────────────────────────

class TestEmailNotification:
    async def test_sends_email_when_alert_email_enabled(self, db, test_user, mock_send_email):
        test_user.alert_email = True
        await db.flush()
        await _make_sub(db, test_user.id, "Netflix", 15.99, 3)

        await generate_upcoming_alerts(db, user_id=test_user.id)
        mock_send_email.assert_awaited_once()

    async def test_no_email_when_alert_email_disabled(self, db, test_user, mock_send_email):
        test_user.alert_email = False
        await db.flush()
        await _make_sub(db, test_user.id, "Netflix", 15.99, 3)

        await generate_upcoming_alerts(db, user_id=test_user.id)
        mock_send_email.assert_not_awaited()

    async def test_no_email_when_no_alerts_created(self, db, test_user, mock_send_email):
        # No subscriptions → no alerts → no email
        await generate_upcoming_alerts(db, user_id=test_user.id)
        mock_send_email.assert_not_awaited()
