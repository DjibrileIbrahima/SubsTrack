from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid_client import client, PLAID_PRODUCTS, PLAID_COUNTRY_CODES
from db.database import get_db
from db.models import User, LinkedAccount
from services.encryption import encrypt, decrypt

router = APIRouter()


class PublicTokenRequest(BaseModel):
    public_token: str
    user_id: str = "default_user"
    institution_name: str = "Unknown Bank"


@router.post("/link-token")
async def create_link_token(user_id: str = "default_user"):
    """Step 1: Create a link token for the frontend Plaid Link widget."""
    try:
        request = LinkTokenCreateRequest(
            products=PLAID_PRODUCTS,
            client_name="SubsTrack",
            country_codes=PLAID_COUNTRY_CODES,
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
        )
        response = client.link_token_create(request)
        return {"link_token": response["link_token"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exchange-token")
async def exchange_public_token(
    body: PublicTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Step 2: Exchange the public token for a permanent access token, encrypt and save to DB."""
    try:
        request = ItemPublicTokenExchangeRequest(public_token=body.public_token)
        response = client.item_public_token_exchange(request)
        access_token = response["access_token"]

        # Encrypt before storing — plain text never touches the DB
        encrypted_token = encrypt(access_token)

        # Get or create user
        result = await db.execute(select(User).where(User.user_id == body.user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(user_id=body.user_id)
            db.add(user)
            await db.flush()

        # Save encrypted access token
        account = LinkedAccount(
            user_id=body.user_id,
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
async def get_accounts(user_id: str = "default_user", db: AsyncSession = Depends(get_db)):
    """List all linked bank accounts for a user. Never exposes access tokens."""
    result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    return {
        "accounts": [
            {
                "id": a.id,
                "institution": a.institution_name,
                "linked_at": a.linked_at,
            }
            for a in accounts
        ]
    }
