import uuid
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from db.models import User

# Dev user constants — replaced by real JWT auth in Phase 8
DEV_USER_EMAIL = "dev@substrack.com"
DEV_USER_PASSWORD = "devpassword"  # hashed below


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    """
    Temporary: returns a fixed dev user for development.
    Phase 8 will replace this with JWT token extraction.
    """
    result = await db.execute(select(User).where(User.email == DEV_USER_EMAIL))
    user = result.scalar_one_or_none()

    if not user:
        # Auto-create dev user on first run
        import bcrypt
        hashed = bcrypt.hashpw(DEV_USER_PASSWORD.encode(), bcrypt.gensalt()).decode()
        user = User(
            email=DEV_USER_EMAIL,
            hashed_password=hashed,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user
