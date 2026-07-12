import logging
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db.database import AsyncSessionLocal

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/health", include_in_schema=False)
async def liveness():
    """Liveness probe — returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
async def readiness():
    """Readiness probe — returns 200 when DB and Redis are reachable, 503 otherwise.

    Used by load balancers and ECS health checks to decide whether to route traffic.
    """
    checks: dict[str, str] = {}

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        # keep exception detail out of the response — it can contain DSNs/credentials
        checks["db"] = "error"
        logger.error("readiness_db_failed", extra={"error": str(exc)})

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            socket_connect_timeout=2,
        )
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = "error"
        logger.error("readiness_redis_failed", extra={"error": str(exc)})

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
    )
