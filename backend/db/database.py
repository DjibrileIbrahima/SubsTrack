import logging
import os
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://substrack:substrack_password@localhost:5432/substrack"
)

_engine_kwargs: dict = {"echo": os.getenv("SQL_ECHO", "false").lower() == "true"}
if DATABASE_URL.startswith("postgresql"):
    # Pool tuning applies only to Postgres; SQLite (tests) keeps its default pool.
    # pre_ping transparently replaces connections dropped by an RDS failover/idle
    # timeout; statement_timeout caps runaway queries so they can't hold the pool.
    _engine_kwargs.update(
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),  # fail fast vs. 30s default
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"server_settings": {"statement_timeout": os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")}},
    )

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# ── Slow-query detection ──────────────────────────────────────────────────────
_query_logger = logging.getLogger("substrack.query")
_SLOW_QUERY_MS = float(os.getenv("SLOW_QUERY_MS", "200"))


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info["_q_start"] = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = conn.info.pop("_q_start", None)
    if start is None:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > _SLOW_QUERY_MS:
        _query_logger.warning(
            "slow_query",
            extra={"duration_ms": round(elapsed_ms, 1), "statement": statement[:300]},
        )


# Dependency for FastAPI routes
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
