import asyncio
import hashlib
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.deps import (
    _TOKEN_MIN_IAT_PREFIX,
    get_current_user,
    get_redis,
    revoke_user_sessions,
)
from db.models import Alert, LinkedAccount, PasswordResetToken, Subscription, Transaction, User
from limiter import limiter
from services import plaid_service
from services.email import send_reset_email
from services.encryption import decrypt, encrypt
from services.jwt import (
    REFRESH_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from services.mfa import encrypt_secret, generate_totp_secret, get_totp_uri, verify_totp


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash_reset_token(token: str) -> str:
    """Reset tokens are stored hashed so a DB leak can't be used for account takeover."""
    return hashlib.sha256(token.encode()).hexdigest()


# bcrypt is ~100-300ms of pure CPU per call; running it inline would block the
# event loop for every concurrent request. Dispatch to a thread like the Plaid SDK.
# A precomputed dummy hash keeps unknown-email logins as slow as real ones, closing
# the user-enumeration timing oracle.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


async def _hash_password(password: str) -> str:
    hashed = await asyncio.to_thread(bcrypt.hashpw, password.encode(), bcrypt.gensalt())
    return hashed.decode()


async def _verify_password(password: str, hashed: str | None) -> bool:
    """Constant-time-ish password check. Always runs bcrypt (against a dummy hash
    when the user or password is absent) so timing doesn't reveal account existence."""
    target = hashed.encode() if hashed else _DUMMY_HASH
    ok = await asyncio.to_thread(bcrypt.checkpw, password.encode(), target)
    return bool(ok) and hashed is not None


def _normalize_email(email: str) -> str:
    """Emails are stored lowercased; Foo@x.com and foo@x.com are one account."""
    return email.strip().lower()


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(func.lower(User.email) == _normalize_email(email))
    )
    return result.scalar_one_or_none()


router = APIRouter()
logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days — access cookie lifespan (JWT exp is shorter)
REFRESH_COOKIE_MAX_AGE = REFRESH_EXPIRE_DAYS * 86400
# The refresh cookie is scoped to /api/auth so it's only ever sent to the
# refresh and logout endpoints, not on every API request.
REFRESH_COOKIE_PATH = "/api/auth"

_MFA_SESSION_TTL = 300  # seconds — how long the temp token is valid after password check
_MFA_SESSION_PREFIX = "mfa_session:"
_REFRESH_FAMILY_PREFIX = "refresh_family:"

# Per-account brute-force lockout. Complements the per-IP limit on /login: with
# real client IPs (see nginx real_ip config), a distributed attack that spreads
# under the per-IP cap is still stopped once it accumulates enough failures
# against one account. Keyed on the normalized email, so unknown and known
# accounts lock identically (no enumeration signal). Temporary and self-clearing;
# the tradeoff is that an attacker can briefly lock a victim's PASSWORD login —
# OAuth is unaffected and the lock lifts after the window.
_LOGIN_FAIL_PREFIX = "login_fail:"
_LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "10"))
_LOGIN_FAIL_WINDOW = int(os.getenv("LOGIN_FAIL_WINDOW_SECONDS", "900"))  # 15 minutes


async def _assert_not_locked_out(redis, email: str) -> None:
    count = await redis.get(f"{_LOGIN_FAIL_PREFIX}{email}")
    if count is not None and int(count) >= _LOGIN_MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts for this account. Try again later.",
            headers={"Retry-After": str(_LOGIN_FAIL_WINDOW)},
        )


async def _record_login_failure(redis, email: str) -> None:
    key = f"{_LOGIN_FAIL_PREFIX}{email}"
    await redis.incr(key)
    # Refresh the TTL on each failure (sliding window): sustained attacks stay
    # locked, while a few stray failures clear themselves after the window.
    await redis.expire(key, _LOGIN_FAIL_WINDOW)


async def _clear_login_failures(redis, email: str) -> None:
    await redis.delete(f"{_LOGIN_FAIL_PREFIX}{email}")


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token", value=token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=COOKIE_MAX_AGE, path="/",
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token", value=token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=REFRESH_COOKIE_MAX_AGE, path=REFRESH_COOKIE_PATH,
    )


async def _issue_session(response: Response, redis, user_id: str) -> None:
    """Mint an access + refresh token pair, register the refresh family in Redis,
    and set both cookies. Used by every successful first-factor completion."""
    family_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    await redis.setex(f"{_REFRESH_FAMILY_PREFIX}{family_id}", REFRESH_COOKIE_MAX_AGE, jti)
    set_auth_cookie(response, create_access_token(user_id))
    set_refresh_cookie(response, create_refresh_token(user_id, family_id, jti))


def _redis() -> aioredis.Redis:
    return aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)


async def _create_mfa_session(user_id: str) -> str:
    """Store a short-lived second-factor session in Redis and return its token."""
    mfa_token = str(uuid.uuid4())
    r = _redis()
    try:
        await r.setex(f"{_MFA_SESSION_PREFIX}{mfa_token}", _MFA_SESSION_TTL, user_id)
    finally:
        await r.aclose()
    return mfa_token


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    response: Response,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    if await _get_user_by_email(db, body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    hashed = await _hash_password(body.password)
    user = User(email=_normalize_email(body.email), hashed_password=hashed)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # concurrent registration with the same email lost the race
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    await db.refresh(user)
    await _issue_session(response, redis, str(user.id))
    return {"email": user.email}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    email = _normalize_email(body.email)
    await _assert_not_locked_out(redis, email)

    user = await _get_user_by_email(db, body.email)
    if not await _verify_password(body.password, user.hashed_password if user else None):
        await _record_login_failure(redis, email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _clear_login_failures(redis, email)

    if user.mfa_enabled and user.mfa_secret:
        mfa_token = await _create_mfa_session(str(user.id))
        return JSONResponse(status_code=202, content={"mfa_required": True, "mfa_token": mfa_token})

    await _issue_session(response, redis, str(user.id))
    return {"email": user.email}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    redis: aioredis.Redis = Depends(get_redis),
):
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_access_token(token)
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                ttl = max(int(exp - datetime.now(UTC).timestamp()), 1)
                await redis.setex(f"token_blocklist:{jti}", ttl, "1")
        except HTTPException:
            pass  # expired token — no need to blocklist

    # Kill the refresh family so the long-lived token can't mint new sessions.
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            rp = decode_refresh_token(refresh_token)
            if rp.get("fid"):
                await redis.delete(f"{_REFRESH_FAMILY_PREFIX}{rp['fid']}")
        except HTTPException:
            pass  # expired/invalid refresh token — nothing to revoke

    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path=REFRESH_COOKIE_PATH)
    return {"message": "Logged out"}


@router.post("/refresh")
@limiter.limit("60/minute")
async def refresh(
    request: Request,
    response: Response,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Rotate the refresh token and issue a new access token.

    Rotation with reuse detection: each refresh mints a new jti for the family
    and stores it as the only valid one. A superseded jti presented later means
    the token was captured and replayed — the whole family is revoked and all of
    the user's sessions are killed.
    """
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = decode_refresh_token(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    family_id = payload.get("fid")
    jti = payload.get("jti")
    if not user_id or not family_id or not jti:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Honour password-reset revocation (token_min_iat) for refresh tokens too.
    min_iat = await redis.get(f"{_TOKEN_MIN_IAT_PREFIX}{user_id}")
    if min_iat is not None:
        iat = payload.get("iat")
        if iat is None or int(iat) < int(min_iat):
            raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    family_key = f"{_REFRESH_FAMILY_PREFIX}{family_id}"
    current_jti = await redis.get(family_key)
    if current_jti is None:
        # Family expired or was revoked (logout / reuse) — force a fresh login.
        raise HTTPException(status_code=401, detail="Refresh session expired")
    if current_jti != jti:
        # A superseded token was replayed → token theft. Burn the family and
        # every session for this user.
        await redis.delete(family_key)
        await revoke_user_sessions(redis, user_id)
        logger.warning("Refresh token reuse detected", extra={"user_id": user_id})
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")

    # Rotate: the new jti becomes the only valid token in the family.
    new_jti = str(uuid.uuid4())
    await redis.setex(family_key, REFRESH_COOKIE_MAX_AGE, new_jti)
    set_auth_cookie(response, create_access_token(user_id))
    set_refresh_cookie(response, create_refresh_token(user_id, family_id, new_jti))
    return {"refreshed": True}


# ── MFA ───────────────────────────────────────────────────────────────────────

@router.get("/mfa/setup")
async def mfa_setup(current_user: User = Depends(get_current_user)):
    """Generate a fresh TOTP secret and QR URI. Does not persist anything — call /mfa/enable to confirm."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, current_user.email)
    return {"secret": secret, "uri": uri}


class MfaEnableRequest(BaseModel):
    secret: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/mfa/enable")
async def mfa_enable(
    body: MfaEnableRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify the TOTP code against the provided secret, then persist and activate MFA."""
    import pyotp
    if not pyotp.TOTP(body.secret).verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code — check your authenticator app")
    current_user.mfa_secret = encrypt_secret(body.secret)
    current_user.mfa_enabled = True
    await db.commit()
    logger.info("mfa_enabled", extra={"user_id": str(current_user.id)})
    return {"mfa_enabled": True}


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/mfa/disable")
async def mfa_disable(
    body: MfaCodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.mfa_enabled or not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    if not verify_totp(current_user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    await db.commit()
    logger.info("mfa_disabled", extra={"user_id": str(current_user.id)})
    return {"mfa_enabled": False}


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/mfa/verify")
@limiter.limit("10/minute")
async def mfa_verify(
    request: Request,
    response: Response,
    body: MfaVerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Second step of MFA login. Validates the temp token from Redis and the TOTP code."""
    r = _redis()
    try:
        user_id_str = await r.get(f"{_MFA_SESSION_PREFIX}{body.mfa_token}")
        if not user_id_str:
            raise HTTPException(status_code=401, detail="MFA session expired — please log in again")
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
        user = result.scalar_one_or_none()
        if not user or not user.mfa_enabled or not user.mfa_secret:
            raise HTTPException(status_code=401, detail="Invalid MFA session")
        if not verify_totp(user.mfa_secret, body.code):
            raise HTTPException(status_code=400, detail="Invalid code")
        await r.delete(f"{_MFA_SESSION_PREFIX}{body.mfa_token}")
    finally:
        await r.aclose()

    await _issue_session(response, redis, str(user.id))
    return {"email": user.email}


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/google")
async def google_login():
    state = secrets.token_urlsafe(32)
    params = (
        f"client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
        f"&state={state}"
    )
    redirect = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    redirect.set_cookie(
        key="oauth_state", value=state,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=300, path="/",
    )
    return redirect


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or not secrets.compare_digest(stored_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    async with httpx.AsyncClient(timeout=10) as http:
        token_response = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            logger.error("Google token exchange failed: %s", token_response.text)
            raise HTTPException(status_code=400, detail="Google authentication failed")
        token_data = token_response.json()
        if "error" in token_data:
            raise HTTPException(status_code=400, detail="Google authentication failed")
        user_info_response = await http.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        if user_info_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user info")
        user_info = user_info_response.json()

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Google")
    # Accounts are matched by email, so an unverified Google email would let an
    # attacker claim someone else's account. Require Google's verification flag.
    if user_info.get("verified_email") is not True:
        logger.warning("Google OAuth rejected: unverified email")
        raise HTTPException(status_code=400, detail="Google account email is not verified")

    user = await _get_user_by_email(db, email)
    if not user:
        user = User(email=_normalize_email(email), hashed_password=None)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # MFA applies regardless of how the first factor was satisfied — OAuth must
    # not become a bypass. Hand off to the same /mfa/verify step as password login.
    if user.mfa_enabled and user.mfa_secret:
        mfa_token = await _create_mfa_session(str(user.id))
        response = RedirectResponse(f"{FRONTEND_URL}/?mfa_token={mfa_token}")
        response.delete_cookie(key="oauth_state", path="/")
        return response

    response = RedirectResponse(f"{FRONTEND_URL}/")
    await _issue_session(response, redis, str(user.id))
    response.delete_cookie(key="oauth_state", path="/")
    return response


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_user_by_email(db, body.email)
    if not user or not user.hashed_password:
        return {"message": "If that email exists, a reset link has been sent"}
    token = secrets.token_urlsafe(32)
    expires = _utcnow() + timedelta(hours=1)
    db.add(PasswordResetToken(user_id=user.id, token=_hash_reset_token(token), expires_at=expires))
    await db.commit()
    reset_url = f"{FRONTEND_URL}?token={token}"
    await send_reset_email(user.email, reset_url)
    return {"message": "If that email exists, a reset link has been sent"}


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == _hash_reset_token(body.token))
    )
    reset = result.scalar_one_or_none()
    if not reset or reset.used or reset.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalar_one()
    user.hashed_password = await _hash_password(body.password)
    reset.used = True
    await db.commit()
    # People reset passwords because they suspect compromise — kill every
    # session issued before this moment.
    await revoke_user_sessions(redis, str(user.id))
    return {"message": "Password updated"}


# ── Plaid ─────────────────────────────────────────────────────────────────────

class PublicTokenRequest(BaseModel):
    public_token: str
    institution_name: str = "Unknown Bank"


@router.post("/link-token")
@limiter.limit("20/minute")
async def create_link_token(request: Request, current_user: User = Depends(get_current_user)):
    try:
        link_token = await plaid_service.create_link_token(str(current_user.id))
        return {"link_token": link_token}
    except Exception:
        logger.exception("Failed to create Plaid link token")
        raise HTTPException(status_code=500, detail="Failed to create link token")


class UpdateLinkTokenRequest(BaseModel):
    account_id: uuid.UUID


@router.post("/link-token/update")
@limiter.limit("10/minute")
async def create_update_link_token(
    request: Request,
    body: UpdateLinkTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an update-mode link token so the user can re-authenticate a broken item."""
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == body.account_id,
            LinkedAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        link_token = await plaid_service.create_link_token(
            str(current_user.id), access_token=decrypt(account.access_token)
        )
        return {"link_token": link_token}
    except Exception:
        logger.exception("Failed to create update-mode link token for account %s", account.id)
        raise HTTPException(status_code=500, detail="Failed to create link token")


@router.post("/exchange-token")
@limiter.limit("10/minute")
async def exchange_public_token(
    request: Request,
    body: PublicTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        access_token, item_id = await plaid_service.exchange_public_token(body.public_token)
        account = LinkedAccount(
            user_id=current_user.id,
            access_token=encrypt(access_token),
            item_id=item_id,
            institution_name=body.institution_name,
        )
        db.add(account)
        await db.commit()
        return {"message": "Bank account connected successfully!"}
    except Exception:
        await db.rollback()
        logger.exception("Failed to exchange Plaid public token")
        raise HTTPException(status_code=500, detail="Failed to connect bank account")


@router.get("/accounts")
async def get_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == current_user.id)
    )
    accounts = result.scalars().all()
    return {
        "accounts": [
            {
                "id": str(a.id),
                "institution": a.institution_name,
                "linked_at": a.linked_at,
                "status": a.status,
            }
            for a in accounts
        ]
    }


@router.delete("/accounts/{account_id}")
async def unlink_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == account_id,
            LinkedAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Revoke at Plaid BEFORE local cleanup: if this fails the account row
    # survives and the user can retry; the reverse order would orphan a live
    # token at Plaid (connection stays open, item billing continues).
    # remove_item treats an already-removed item as success, so retries work.
    try:
        await plaid_service.remove_item(decrypt(account.access_token))
    except Exception:
        logger.exception("Plaid item removal failed for account %s", account_id)
        raise HTTPException(
            status_code=502,
            detail="Failed to disconnect the bank from Plaid. Please try again.",
        )

    try:
        # Only deactivate subscriptions that came from THIS bank. Legacy rows
        # (linked_account_id NULL, from before attribution existed) are swept
        # only when this is the user's last linked account — with no banks
        # left, no plaid subscription can still be live.
        count_result = await db.execute(
            select(LinkedAccount.id).where(LinkedAccount.user_id == current_user.id)
        )
        is_last_account = len(count_result.scalars().all()) == 1

        scope = Subscription.linked_account_id == account.id
        if is_last_account:
            scope = scope | (Subscription.linked_account_id == None)  # noqa: E711

        subs_result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == current_user.id,
                Subscription.source == "plaid",
                Subscription.is_active == True,  # noqa: E712
                scope,
            )
        )
        for sub in subs_result.scalars().all():
            sub.is_active = False

        await db.delete(account)
        await db.commit()
        return {"message": "Account unlinked"}
    except Exception:
        await db.rollback()
        logger.exception("Failed to unlink account %s", account_id)
        raise HTTPException(status_code=500, detail="Failed to unlink account")


# ── Profile ───────────────────────────────────────────────────────────────────

def _serialize_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "alert_email": user.alert_email,
        "alert_sms": user.alert_sms,
        "phone": user.phone,
        "mfa_enabled": user.mfa_enabled,
        # Lets the UI know whether to ask for a password on account deletion
        # (OAuth-only users have none).
        "has_password": user.hashed_password is not None,
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return _serialize_user(current_user)


class UpdateMeRequest(BaseModel):
    alert_email: bool | None = None
    alert_sms: bool | None = None
    phone: str | None = Field(default=None, max_length=20)


@router.patch("/me")
async def update_me(
    body: UpdateMeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.alert_email is not None:
        current_user.alert_email = body.alert_email
    if body.alert_sms is not None:
        current_user.alert_sms = body.alert_sms
    if body.phone is not None:
        current_user.phone = body.phone
    await db.commit()
    await db.refresh(current_user)
    return _serialize_user(current_user)


class DeleteAccountRequest(BaseModel):
    password: str | None = None
    code: str | None = None


@router.post("/delete-account")
@limiter.limit("5/minute")
async def delete_account(
    request: Request,
    response: Response,
    body: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete the current user's account and all associated data.

    Irreversible, so password users must re-enter their password. Every Plaid
    item is revoked first (all-or-nothing, like unlink) so deletion never orphans
    a live token at Plaid.
    """
    # Re-authenticate password users. OAuth-only users have no password; the
    # session cookie plus CSRF/Origin checks are the proof of intent there.
    if current_user.hashed_password:
        if not body.password or not await _verify_password(body.password, current_user.hashed_password):
            raise HTTPException(status_code=403, detail="Password is incorrect")

    # If MFA is enabled, require a current TOTP too — same second factor that
    # gates login must gate this irreversible action.
    if current_user.mfa_enabled and current_user.mfa_secret:
        if not body.code or not verify_totp(current_user.mfa_secret, body.code):
            raise HTTPException(status_code=403, detail="Invalid two-factor code")

    user_id = current_user.id

    accounts = (
        await db.execute(select(LinkedAccount).where(LinkedAccount.user_id == user_id))
    ).scalars().all()
    for account in accounts:
        try:
            await plaid_service.remove_item(decrypt(account.access_token))
        except Exception:
            logger.exception("Plaid item removal failed during account deletion for user %s", user_id)
            raise HTTPException(
                status_code=502,
                detail="Couldn't disconnect a bank from Plaid. Please try again.",
            )

    # Explicit FK-safe deletes: async SQLAlchemy can't lazy-load ORM relationship
    # cascades during flush, so delete children directly, in dependency order.
    await db.execute(delete(Alert).where(Alert.user_id == user_id))
    await db.execute(delete(Transaction).where(Transaction.user_id == user_id))
    await db.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    await db.execute(delete(LinkedAccount).where(LinkedAccount.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()

    # Tear down the session: revoke the refresh family and clear both cookies.
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            rp = decode_refresh_token(refresh_token)
            if rp.get("fid"):
                await redis.delete(f"{_REFRESH_FAMILY_PREFIX}{rp['fid']}")
        except HTTPException:
            pass
    await revoke_user_sessions(redis, str(user_id))
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path=REFRESH_COOKIE_PATH)

    logger.info("account_deleted", extra={"user_id": str(user_id)})
    return {"message": "Account deleted"}
