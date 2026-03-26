import uuid
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
from db.deps import get_current_user
from services.encryption import encrypt

router = APIRouter()


class PublicTokenRequest(BaseModel):
    public_token: str
    institution_name: str = "Unknown Bank"


@router.post("/link-token")
async def create_link_token(
    current_user: User = Depends(get_current_user)
):
    """Create a Plaid link token for the current user."""
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
    """Exchange public token for encrypted access token and save to DB."""
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
    """List all linked bank accounts. Never exposes access tokens."""
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
            }
            for a in accounts
        ]
    }
