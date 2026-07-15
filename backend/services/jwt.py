import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
# Access tokens are now short-lived; long-lived sessions ride on rotating
# refresh tokens (see routes/auth.py). Old default was 7 days.
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", 30))
REFRESH_EXPIRE_DAYS = int(os.getenv("REFRESH_EXPIRE_DAYS", 7))

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set in your .env file.")


def create_access_token(user_id: str) -> str:
    """Create a signed short-lived access JWT for a user.

    iat enables per-user revocation: tokens issued before a user's
    token_min_iat marker (see db/deps.py) are rejected. typ distinguishes
    access from refresh tokens so one can't be substituted for the other.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, family_id: str, jti: str) -> str:
    """Create a long-lived refresh JWT.

    family_id ties a rotation chain together; jti is the single valid token in
    that chain at any moment (tracked in Redis). Presenting a superseded jti
    signals theft and revokes the whole family — see routes/auth.py refresh().
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(days=REFRESH_EXPIRE_DAYS),
        "jti": jti,
        "fid": family_id,
        "typ": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify an access JWT. Returns the full payload dict.
    Rejects refresh tokens so they can't be used to authenticate requests.
    Raises HTTPException on expiry or invalid signature."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        if payload.get("typ") == "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_refresh_token(token: str) -> dict:
    """Decode and verify a refresh JWT. Rejects access tokens.
    Raises HTTPException on expiry or invalid signature."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not payload.get("sub") or payload.get("typ") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
