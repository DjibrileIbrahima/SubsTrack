import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

from observability import configure_logging, init_sentry  # noqa: E402

configure_logging()
init_sentry()

from arq import cron  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from services.alert_service import generate_upcoming_alerts  # noqa: E402

logger = logging.getLogger(__name__)


async def run_alert_job(ctx):
    job_id = ctx.get("job_id", "unknown")
    start = time.perf_counter()
    logger.info("job_start", extra={"job": "run_alert_job", "job_id": job_id})

    async with AsyncSessionLocal() as db:
        try:
            count = await generate_upcoming_alerts(db)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "job_complete",
                extra={
                    "job": "run_alert_job",
                    "job_id": job_id,
                    "alerts_created": count,
                    "duration_ms": elapsed_ms,
                },
            )
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            # logger.exception at ERROR level triggers Sentry capture via LoggingIntegration
            logger.exception(
                "job_failed",
                extra={"job": "run_alert_job", "job_id": job_id, "duration_ms": elapsed_ms},
            )


async def on_startup(ctx):
    logger.info("worker_started", extra={"redis_url": os.getenv("REDIS_URL", "redis://localhost:6379")})


async def on_shutdown(ctx):
    logger.info("worker_stopped")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
    functions = [run_alert_job]
    cron_jobs = [cron(run_alert_job, hour=8, minute=0)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = 3
    job_timeout = 300
