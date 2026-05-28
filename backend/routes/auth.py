import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.deps import get_current_user
from db.models import LinkedAccount, PasswordResetToken, User
from limiter import limiter
from plaid_client import PLAID_COUNTRY_CODES, PLAID_PRODUCTS, client
from services.email import send_reset_email
from services.encryption import encrypt
from services.jwt import create_access_token


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


router = APIRouter()
logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token", value=token,
        httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=COOKIE_MAX_AGE, path="/",
    )

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
    await db.commit()
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
    token = create_access_token(str(user.id))
    set_auth_cookie(response, token)
    return {"email": user.email}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}


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

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=email, hashed_password=None)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_access_token(str(user.id))
    response = RedirectResponse(f"{FRONTEND_URL}/")
    set_auth_cookie(response, token)
    response.delete_cookie(key="oauth_state", path="/")
    return response

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    # Always return 200 to prevent email enumeration
    if not user or not user.hashed_password:
        return {"message": "If that email exists, a reset link has been sent"}
    token = secrets.token_urlsafe(32)
    expires = _utcnow() + timedelta(hours=1)
    db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires))
    await db.commit()
    reset_url = f"{FRONTEND_URL}?token={token}"
    await send_reset_email(user.email, reset_url)
    return {"message": "If that email exists, a reset link has been sent"}


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == body.token)
    )
    reset = result.scalar_one_or_none()
    if not reset or reset.used or reset.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalar_one()
    user.hashed_password = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    reset.used = True
    await db.commit()
    return {"message": "Password updated"}


class PublicTokenRequest(BaseModel):
    public_token: str
    institution_name: str = "Unknown Bank"


@router.post("/link-token")
@limiter.limit("20/minute")
async def create_link_token(request: Request, current_user: User = Depends(get_current_user)):
    try:
        request = LinkTokenCreateRequest(
            products=PLAID_PRODUCTS,
            client_name="SubsTrack",
            country_codes=PLAID_COUNTRY_CODES,
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=str(current_user.id)),
        )
        response = client.link_token_create(request)
        return {"link_token": response["link_token"]}
    except Exception:
        logger.exception("Failed to create Plaid link token")
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
        request = ItemPublicTokenExchangeRequest(public_token=body.public_token)
        response = client.item_public_token_exchange(request)
        encrypted_token = encrypt(response["access_token"])
        account = LinkedAccount(
            user_id=current_user.id,
            access_token=encrypted_token,
            item_id=response.get("item_id"),
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
            {"id": str(a.id), "institution": a.institution_name, "linked_at": a.linked_at}
            for a in accounts
        ]
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "alert_email": current_user.alert_email,
        "alert_sms": current_user.alert_sms,
        "phone": current_user.phone,
    }


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
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "alert_email": current_user.alert_email,
        "alert_sms": current_user.alert_sms,
        "phone": current_user.phone,
    }
