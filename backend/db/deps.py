import os
import time
import uuid
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import User
from services.jwt import REFRESH_EXPIRE_DAYS, decode_access_token

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis_pool: aioredis.Redis | None = None

_TOKEN_MIN_IAT_PREFIX = "token_min_iat:"


def _get_redis_pool() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    yield _get_redis_pool()


async def revoke_user_sessions(redis: aioredis.Redis, user_id: str) -> None:
    """Invalidate every access AND refresh token issued before now for this user
    (e.g. after a password reset). The marker's TTL covers the refresh window —
    the longest-lived token carrying an iat — so it can't expire while a
    pre-reset refresh token is still alive."""
    await redis.setex(
        f"{_TOKEN_MIN_IAT_PREFIX}{user_id}", REFRESH_EXPIRE_DAYS * 86400, int(time.time())
    )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(token)
    jti = payload.get("jti")
    if jti and await redis.get(f"token_blocklist:{jti}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    min_iat = await redis.get(f"{_TOKEN_MIN_IAT_PREFIX}{payload['sub']}")
    if min_iat is not None:
        iat = payload.get("iat")
        # Tokens without iat predate revocation support — fail closed.
        if iat is None or int(iat) < int(min_iat):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
