import logging
import os

from dotenv import load_dotenv

load_dotenv()

from arq import cron  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from services.alert_service import generate_upcoming_alerts  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_alert_job(ctx):
    async with AsyncSessionLocal() as db:
        try:
            count = await generate_upcoming_alerts(db)
            logger.info("Alert job complete: %d new alert(s)", count)
        except Exception:
            logger.exception("Alert job failed")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379")
    )
    functions = [run_alert_job]
    cron_jobs = [cron(run_alert_job, hour=8, minute=0)]
    max_tries = 3        # retry a failed job up to 3 times before giving up
    job_timeout = 300    # cancel any job that runs longer than 5 minutes
