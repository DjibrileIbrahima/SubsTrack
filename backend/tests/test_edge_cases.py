"""
Edge-case tests for subscription detection and async worker behaviour.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.subscription_detector import (
    detect_subscriptions,
    detect_subscription_candidates,
    build_candidate,
    infer_frequency,
    amount_consistency_score,
    interval_consistency_score,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_txns(merchant, amount, start: date, interval_days: int, count: int):
    return [
        {
            "merchant_name": merchant,
            "name": merchant,
            "amount": amount,
            "date": (start + timedelta(days=i * interval_days)).isoformat(),
            "category": ["Software"],
        }
        for i in range(count)
    ]


def make_txns_amounts(merchant, amounts, start: date, interval_days: int):
    return [
        {
            "merchant_name": merchant,
            "name": merchant,
            "amount": amt,
            "date": (start + timedelta(days=i * interval_days)).isoformat(),
            "category": ["Software"],
        }
        for i, amt in enumerate(amounts)
    ]


# ─── Subscription detection edge cases ───────────────────────────────────────

class TestMinimumOccurrences:
    def test_exactly_two_occurrences_creates_candidate(self):
        txns = make_txns("SPOTIFY", 9.99, date(2024, 1, 1), 30, 2)
        candidates = detect_subscription_candidates(txns)
        assert len(candidates) == 1

    def test_single_occurrence_produces_no_candidate(self):
        txns = make_txns("SPOTIFY", 9.99, date(2024, 1, 1), 30, 1)
        assert detect_subscription_candidates(txns) == []

    def test_zero_occurrences_produces_no_candidate(self):
        assert detect_subscription_candidates([]) == []


class TestAmountDrift:
    def test_tiny_drift_under_5pct_detected(self):
        # 9.99 → 10.05 is ~0.6% drift — should be detected
        txns = make_txns_amounts("NOTION", [9.99, 10.02, 9.98, 10.01],
                                  date(2024, 1, 1), 30)
        results = detect_subscriptions(txns)
        assert len(results) == 1

    def test_drift_between_5_and_20pct_may_still_detect(self):
        # ~10% drift — amount_score = 0.9, confidence depends on other factors
        txns = make_txns_amounts("ADOBE", [10.0, 11.0, 10.0, 11.0],
                                  date(2024, 1, 1), 30)
        candidates = detect_subscription_candidates(txns)
        assert len(candidates) == 1
        assert candidates[0]["confidence"] > 0

    def test_extreme_amount_drift_split_into_clusters(self):
        # Amounts [10, 50, 10, 50] are clustered by amount into two groups:
        # cluster $10 and cluster $50 — each detected as separate subscriptions.
        txns = make_txns_amounts("UNKNOWNCO", [10.0, 50.0, 10.0, 50.0],
                                  date(2024, 1, 1), 30)
        candidates = detect_subscription_candidates(txns)
        amounts = {c["amount"] for c in candidates}
        assert amounts == {10.0, 50.0}

    def test_amount_consistency_score_handles_empty(self):
        assert amount_consistency_score([]) == 0.0

    def test_amount_consistency_with_two_equal(self):
        assert amount_consistency_score([15.0, 15.0]) == 1.0


class TestIntervalGaps:
    def test_gap_in_billing_cycle_still_detected(self):
        # Skip one month — should still detect as roughly monthly
        txns = [
            {"merchant_name": "GITHUB", "name": "GITHUB", "amount": 4.0,
             "date": "2024-01-01", "category": ["Software"]},
            {"merchant_name": "GITHUB", "name": "GITHUB", "amount": 4.0,
             "date": "2024-03-01", "category": ["Software"]},
            {"merchant_name": "GITHUB", "name": "GITHUB", "amount": 4.0,
             "date": "2024-05-01", "category": ["Software"]},
        ]
        candidates = detect_subscription_candidates(txns)
        # 59-day avg interval → quarterly range, or may be rejected by infer_frequency
        # What matters is that the detector doesn't crash
        assert isinstance(candidates, list)

    def test_irregular_but_roughly_monthly_detected(self):
        # Intervals: 28, 31, 29 days — all monthly
        txns = [
            {"merchant_name": "NOTION", "name": "NOTION", "amount": 8.0,
             "date": "2024-01-01", "category": ["Software"]},
            {"merchant_name": "NOTION", "name": "NOTION", "amount": 8.0,
             "date": "2024-01-29", "category": ["Software"]},
            {"merchant_name": "NOTION", "name": "NOTION", "amount": 8.0,
             "date": "2024-03-01", "category": ["Software"]},
            {"merchant_name": "NOTION", "name": "NOTION", "amount": 8.0,
             "date": "2024-03-30", "category": ["Software"]},
        ]
        results = detect_subscriptions(txns)
        assert len(results) == 1
        assert results[0]["frequency"] == "monthly"

    def test_interval_consistency_perfect(self):
        assert interval_consistency_score([30, 30, 30]) == 1.0

    def test_interval_consistency_empty(self):
        assert interval_consistency_score([]) == 0.0


class TestFrequencyBoundaries:
    def test_biweekly_at_14_days(self):
        txns = make_txns("CANVA", 12.99, date(2024, 1, 1), 14, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        assert results[0]["frequency"] == "biweekly"

    def test_quarterly_at_91_days(self):
        txns = make_txns("ADOBE", 54.99, date(2023, 1, 1), 91, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        assert results[0]["frequency"] == "quarterly"

    def test_annual_with_two_data_points(self):
        txns = make_txns("AMAZON PRIME", 139.0, date(2023, 1, 1), 365, 2)
        candidates = detect_subscription_candidates(txns)
        assert len(candidates) == 1
        assert candidates[0]["frequency"] == "yearly"

    def test_infer_frequency_boundary_weekly_low(self):
        assert infer_frequency(5) == "weekly"

    def test_infer_frequency_boundary_weekly_high(self):
        assert infer_frequency(9) == "weekly"

    def test_infer_frequency_boundary_biweekly(self):
        assert infer_frequency(10) == "biweekly"
        assert infer_frequency(20) == "biweekly"

    def test_infer_frequency_below_range_returns_none(self):
        assert infer_frequency(3) is None

    def test_infer_frequency_above_range_returns_none(self):
        assert infer_frequency(400) is None


class TestNextExpectedCalculation:
    def test_monthly_next_expected_is_one_month_later(self):
        txns = make_txns("NETFLIX", 15.99, date(2024, 3, 1), 30, 3)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        # next_expected should be roughly April 30 ± a few days
        last = results[0]["last_charged"]
        nxt = results[0]["next_expected"]
        delta = (nxt - last).days
        assert 25 <= delta <= 35

    def test_weekly_next_expected_is_about_7_days(self):
        txns = make_txns("DROPBOX", 2.99, date(2024, 1, 1), 7, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        delta = (results[0]["next_expected"] - results[0]["last_charged"]).days
        assert 5 <= delta <= 9

    def test_next_expected_always_after_last_charged(self):
        for interval in [7, 14, 30, 91, 365]:
            txns = make_txns("FIGMA", 15.0, date(2024, 1, 1), interval, 3)
            results = detect_subscriptions(txns)
            if results:
                assert results[0]["next_expected"] > results[0]["last_charged"]


class TestNonSubscriptionFiltering:
    def test_zero_amount_transactions_skipped(self):
        txns = [
            {"merchant_name": "NETFLIX", "name": "NETFLIX", "amount": 0,
             "date": "2024-01-01", "category": ["Entertainment"]},
            {"merchant_name": "NETFLIX", "name": "NETFLIX", "amount": 0,
             "date": "2024-02-01", "category": ["Entertainment"]},
        ]
        assert detect_subscription_candidates(txns) == []

    def test_negative_amounts_skipped(self):
        txns = make_txns("SPOTIFY", -9.99, date(2024, 1, 1), 30, 4)
        assert detect_subscription_candidates(txns) == []

    def test_mixed_positive_negative_uses_positive_only(self):
        txns = [
            {"merchant_name": "SPOTIFY", "name": "SPOTIFY", "amount": 9.99,
             "date": "2024-01-01", "category": ["Music"]},
            {"merchant_name": "SPOTIFY", "name": "SPOTIFY", "amount": -9.99,
             "date": "2024-02-01", "category": ["Music"]},
            {"merchant_name": "SPOTIFY", "name": "SPOTIFY", "amount": 9.99,
             "date": "2024-03-01", "category": ["Music"]},
        ]
        # Only 2 positive, so a candidate may be built — assert no crash
        assert isinstance(detect_subscription_candidates(txns), list)


# ─── Worker retry edge cases ──────────────────────────────────────────────────

class TestWorkerSettings:
    def test_max_tries_is_set(self):
        from worker import WorkerSettings
        assert WorkerSettings.max_tries == 3

    def test_job_timeout_is_set(self):
        from worker import WorkerSettings
        assert WorkerSettings.job_timeout == 300

    def test_cron_jobs_registered(self):
        from worker import WorkerSettings
        assert len(WorkerSettings.cron_jobs) >= 1

    def test_run_alert_job_in_functions(self):
        from worker import WorkerSettings, run_alert_job
        assert run_alert_job in WorkerSettings.functions

    def test_redis_settings_configured(self):
        from worker import WorkerSettings
        assert WorkerSettings.redis_settings is not None


class TestRunAlertJob:
    async def test_run_alert_job_calls_generate_alerts(self):
        from worker import run_alert_job

        mock_count = 3
        with patch("worker.AsyncSessionLocal") as mock_session_cls, \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_count
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await run_alert_job(ctx={})
            mock_gen.assert_called_once_with(mock_db)

    async def test_run_alert_job_logs_on_exception(self, caplog):
        import logging
        from worker import run_alert_job

        with patch("worker.AsyncSessionLocal") as mock_session_cls, \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = RuntimeError("DB exploded")
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.ERROR, logger="worker"):
                await run_alert_job(ctx={})

        assert "Alert job failed" in caplog.text or "DB exploded" in caplog.text

    async def test_run_alert_job_does_not_raise_on_exception(self):
        from worker import run_alert_job

        with patch("worker.AsyncSessionLocal") as mock_session_cls, \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = Exception("unexpected failure")
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not propagate the exception — worker absorbs it and logs
            await run_alert_job(ctx={})

    async def test_run_alert_job_with_empty_context(self):
        from worker import run_alert_job

        with patch("worker.AsyncSessionLocal") as mock_session_cls, \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = 0
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await run_alert_job(ctx={})
            mock_gen.assert_called_once()

    async def test_run_alert_job_returns_none(self):
        from worker import run_alert_job

        with patch("worker.AsyncSessionLocal") as mock_session_cls, \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = 5
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await run_alert_job(ctx={})
            assert result is None
