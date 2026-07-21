import hashlib
import hmac
import logging
import time

import httpx
import jwt
from jwt.algorithms import ECAlgorithm

from plaid_client import PLAID_ENV

logger = logging.getLogger(__name__)

_jwk_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 300  # seconds
_MAX_AGE = 300    # reject tokens older than 5 minutes

_JWK_BASE = {
    "sandbox": "https://sandbox.plaid.com/webhook/v2/verification_keys/",
    "production": "https://production.plaid.com/webhook/v2/verification_keys/",
}


async def _fetch_jwk(kid: str) -> str:
    base = _JWK_BASE.get(PLAID_ENV, _JWK_BASE["sandbox"])
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(base + kid)
        resp.raise_for_status()
        return resp.text


async def _get_public_key(kid: str, force_refresh: bool = False):
    now = time.time()
    cached = _jwk_cache.get(kid)
    if cached and not force_refresh:
        jwk_str, fetched_at = cached
        if now - fetched_at < _CACHE_TTL:
            return ECAlgorithm.from_jwk(jwk_str)

    jwk_str = await _fetch_jwk(kid)
    _jwk_cache[kid] = (jwk_str, now)
    return ECAlgorithm.from_jwk(jwk_str)


async def verify_plaid_webhook(token: str, raw_body: bytes) -> None:
    """Verify a Plaid webhook JWT. Raises ValueError on failure."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise ValueError(f"Invalid JWT header: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise ValueError("JWT header missing 'kid'")

    # Try cached key first, refresh once on signature failure (handles key rotation)
    claims = None
    for attempt, force_refresh in enumerate([False, True]):
        try:
            public_key = await _get_public_key(kid, force_refresh=force_refresh)
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                options={"verify_exp": False},
            )
            break
        except jwt.InvalidSignatureError:
            if attempt == 0:
                logger.warning("Webhook JWT signature invalid with cached key — retrying with fresh key")
                continue
            raise ValueError("JWT signature verification failed")
        except jwt.PyJWTError as exc:
            raise ValueError(f"JWT decode error: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Could not fetch verification key {kid!r} (status {exc.response.status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not fetch verification key {kid!r}: {exc}") from exc

    iat = claims.get("iat")
    if iat is None:
        raise ValueError("JWT missing 'iat' claim")
    if time.time() - iat > _MAX_AGE:
        raise ValueError(f"JWT too old (iat={iat})")

    expected_hash = claims.get("request_body_sha256")
    if not expected_hash:
        raise ValueError("JWT missing 'request_body_sha256' claim")

    actual_hash = hashlib.sha256(raw_body).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise ValueError("Request body hash mismatch")
