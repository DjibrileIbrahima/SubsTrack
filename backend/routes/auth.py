import os
import httpx
import bcrypt
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid_client import client, PLAID_PRODUCTS, PLAID_COUNTRY_CODES
from db.database import get_db
from db.models import User, LinkedAccount
from db.deps import get_current_user
from services.encryption import encrypt
from services.jwt import create_access_token

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
    return {"access_token": token, "token_type": "bearer", "email": user.email}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer", "email": user.email}


@router.get("/google")
async def google_login():
    params = (
        f"client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    async with httpx.AsyncClient() as http:
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
        token_data = token_response.json()
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data["error"])
        user_info_response = await http.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        user_info = user_info_response.json()

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Google")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=email, hashed_password="google_oauth")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_access_token(str(user.id))
    response = RedirectResponse(f"{FRONTEND_URL}/auth/callback")
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,   # change to True in production with HTTPS
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )
    return response

class PublicTokenRequest(BaseModel):
    public_token: str
    institution_name: str = "Unknown Bank"


@router.post("/link-token")
async def create_link_token(current_user: User = Depends(get_current_user)):
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exchange-token")
async def exchange_public_token(
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
            institution_name=body.institution_name,
        )
        db.add(account)
        await db.commit()
        return {"message": "Bank account connected successfully!"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


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
    }