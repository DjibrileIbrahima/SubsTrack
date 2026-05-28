"""
Global pytest configuration and shared fixtures for the SubsTracker backend test suite.

IMPORTANT: Environment variables are set at the very top of this file, BEFORE any backend
module is imported, so that jwt.py, encryption.py, and limiter.py pick up test values at
module-load time rather than at test-run time.
"""

import os

from cryptography.fernet import Fernet

# ─── Set env vars BEFORE importing any backend module ────────────────────────
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-that-is-long-enough!!")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# Use a valid Redis DSN (arq's RedisSettings.from_dsn rejects "memory://").
# The rate limiter bypass means the limiter storage backend is never actually hit.
# The worker tests mock AsyncSessionLocal, so no real Redis connection is made.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("PLAID_CLIENT_ID", "test-client-id")
os.environ.setdefault("PLAID_SECRET", "test-secret")
os.environ["COOKIE_SECURE"] = "false"

# ─── Bypass rate limiting for all tests ──────────────────────────────────────
# The @limiter.limit() decorator calls _check_request_limit at request time,
# so patching it at the class level here (before any request is made) disables
# rate limiting across the entire test suite without touching route decorators.
try:
    from slowapi.extension import Limiter as _SlowApiLimiter

    # Must be a regular (non-async) function — slowapi calls it without await.
    # Must set view_rate_limit on request.state — _inject_headers reads it afterwards.
    def _noop_rate_check(self, request, *args, **kwargs):
        try:
            request.state.view_rate_limit = None
        except Exception:
            pass

    _SlowApiLimiter._check_request_limit = _noop_rate_check
except Exception:
    pass  # safe fallback

# ─── Now import backend modules ───────────────────────────────────────────────
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base, get_db
from db.models import LinkedAccount, Subscription, User
from main import app
from services.encryption import encrypt as _encrypt
from services.jwt import create_access_token

# ─── Database fixture ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """
    Creates a fresh in-memory SQLite database for each test, guaranteeing
    full isolation without requiring a real Postgres instance in CI.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


# ─── HTTP client fixtures ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db):
    """Unauthenticated ASGI test client wired to the test database."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client, test_user):
    """Client with a valid auth cookie for test_user."""
    token = create_access_token(str(test_user.id))
    client.cookies.set("access_token", token)
    return client


# ─── Entity fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user(db):
    hashed = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    user = User(email="test@example.com", hashed_password=hashed)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user2(db):
    """Second user for cross-user data-isolation tests."""
    hashed = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    user = User(email="other@example.com", hashed_password=hashed)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_subscription(db, test_user):
    sub = Subscription(
        user_id=test_user.id,
        merchant="Netflix",
        amount=15.99,
        frequency="monthly",
        next_expected=date.today() + timedelta(days=5),
        category="Entertainment",
        source="manual",
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    return sub


@pytest_asyncio.fixture
async def test_account(db, test_user):
    account = LinkedAccount(
        user_id=test_user.id,
        access_token=_encrypt("access-sandbox-fake-token"),
        item_id="item-sandbox-test-001",
        institution_name="Test Bank",
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


# ─── Global autouse mocks ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_send_email():
    """Prevent real email sends in all tests."""
    with patch("services.alert_service.send_alert_email", new_callable=AsyncMock) as m:
        m.return_value = True
        yield m
