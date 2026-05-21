import os
import logging
from dotenv import load_dotenv

load_dotenv()

from arq import cron
from arq.connections import RedisSettings
from db.database import AsyncSessionLocal
from services.alert_service import generate_upcoming_alerts

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
    # unique=True (default) prevents duplicate enqueues across multiple worker instances
    cron_jobs = [cron(run_alert_job, hour=8, minute=0)]
