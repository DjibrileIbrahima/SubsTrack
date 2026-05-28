"""Tests for the arq background worker (worker.py)."""

from unittest.mock import AsyncMock, patch


class TestRunAlertJob:
    async def test_calls_generate_upcoming_alerts(self):
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        with patch("worker.AsyncSessionLocal", return_value=mock_db), \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = 3

            from worker import run_alert_job
            await run_alert_job({})  # arq passes a context dict

        mock_gen.assert_awaited_once_with(mock_db)

    async def test_logs_result_count(self, caplog):
        import logging
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        with patch("worker.AsyncSessionLocal", return_value=mock_db), \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = 5

            with caplog.at_level(logging.INFO, logger="worker"):
                from worker import run_alert_job
                await run_alert_job({})

        assert "5" in caplog.text

    async def test_handles_exception_gracefully(self, caplog):
        """Worker job must not propagate exceptions — it should log and continue."""
        import logging
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        with patch("worker.AsyncSessionLocal", return_value=mock_db), \
             patch("worker.generate_upcoming_alerts", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = RuntimeError("DB connection lost")

            with caplog.at_level(logging.ERROR, logger="worker"):
                from worker import run_alert_job
                # Must NOT raise
                await run_alert_job({})

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


class TestWorkerSettings:
    def test_has_run_alert_job_in_functions(self):
        from worker import WorkerSettings, run_alert_job
        assert run_alert_job in WorkerSettings.functions

    def test_cron_jobs_configured(self):
        from worker import WorkerSettings
        assert len(WorkerSettings.cron_jobs) >= 1

    def test_cron_scheduled_at_8am(self):
        from worker import WorkerSettings
        cron_job = WorkerSettings.cron_jobs[0]
        # arq CronJob stores hour/minute as int or set depending on version
        assert cron_job.hour in (8, {8})
        assert cron_job.minute in (0, {0})

    def test_redis_settings_from_env(self):
        from worker import WorkerSettings
        # Should use REDIS_URL from environment
        assert WorkerSettings.redis_settings is not None
