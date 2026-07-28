"""Shared arq job-enqueue helpers.

Both the Plaid webhook route and the manual "Sync" button route need to
kick off the same durable, off-request transaction sync — this module is
the one place that owns the arq connection pool.
"""

import os

from arq import create_pool
from arq.connections import RedisSettings

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_arq_pool = None


async def enqueue_item_sync(item_id: str) -> None:
    """Enqueue a durable transaction sync on the arq worker.

    Runs on the arq worker instead of in-process so a sync survives a web-process
    restart: the job lives in Redis and is retried on failure. The _job_id makes
    it idempotent — a burst of triggers (webhook + manual button) for the same
    item collapses into one queued job while the first is still pending or
    running.
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(_REDIS_URL))
    await _arq_pool.enqueue_job("sync_item_job", item_id, _job_id=f"sync:{item_id}")
