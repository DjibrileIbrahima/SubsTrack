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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.deps import get_current_user, get_redis, revoke_user_sessions
from db.models import LinkedAccount, PasswordResetToken, Subscription, User
from limiter import limiter
from services import plaid_service
from services.email import send_reset_email
from services.encryption import decrypt, encrypt
from services.jwt import create_access_token, decode_access_token
from services.mfa import encrypt_secret, generate_totp_secret, get_totp_uri, verify_totp


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash_reset_token(token: str) -> str:
    """Reset tokens are stored hashed so a DB leak can't be used for account takeover."""
    return hashlib.sha256(token.encode()).hexdigest()


router = APIRouter()
logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

_MFA_SESSION_TTL = 300  # seconds — how long the temp token is valid after password check
_MFA_SESSION_PREFIX = "mfa_session:"


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token", value=token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=COOKIE_MAX_AGE, path="/",
    )


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
async def register(request: Request, response: Response, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = User(email=body.email, hashed_password=hashed)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # concurrent registration with the same email lost the race
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    await db.refresh(user)
    token = create_access_token(str(user.id))
    set_auth_cookie(response, token)
    return {"email": user.email}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.mfa_enabled and user.mfa_secret:
        mfa_token = await _create_mfa_session(str(user.id))
        return JSONResponse(status_code=202, content={"mfa_required": True, "mfa_token": mfa_token})

    token = create_access_token(str(user.id))
    set_auth_cookie(response, token)
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
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}


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

    token = create_access_token(str(user.id))
    set_auth_cookie(response, token)
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
async def google_callback(code: str, state: str, request: Request, db: AsyncSession = Depends(get_db)):
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

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=email, hashed_password=None)
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

    token = create_access_token(str(user.id))
    response = RedirectResponse(f"{FRONTEND_URL}/")
    set_auth_cookie(response, token)
    response.delete_cookie(key="oauth_state", path="/")
    return response


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
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
    user.hashed_password = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
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
