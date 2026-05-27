"""Tests for rate limiter configuration and 429 error handling."""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from unittest.mock import MagicMock


class TestLimiterConfig:
    def test_limiter_uses_remote_address(self):
        from limiter import limiter
        assert limiter._key_func is get_remote_address

    def test_limiter_storage_uri_is_redis(self):
        import os
        from limiter import limiter
        expected = os.getenv("REDIS_URL", "redis://localhost:6379")
        assert limiter._storage_uri == expected

    def test_limiter_is_registered_on_app(self):
        from main import app
        from limiter import limiter
        assert app.state.limiter is limiter

    def test_rate_limit_exceeded_handler_registered(self):
        from main import app
        from slowapi.errors import RateLimitExceeded
        assert RateLimitExceeded in app.exception_handlers


def _make_rate_limit_exc(description: str = "5 per minute") -> RateLimitExceeded:
    """Build a RateLimitExceeded with a properly-shaped limit mock."""
    mock_limit = MagicMock()
    mock_limit.error_message = None  # falsy → falls back to str(limit.limit)
    mock_limit.limit.__str__ = lambda self: description
    return RateLimitExceeded(mock_limit)


class TestRateLimitExceededHandler:
    def test_rate_limit_exceeded_is_http_429(self):
        exc = _make_rate_limit_exc("5 per minute")
        assert exc.status_code == 429

    def test_rate_limit_exceeded_detail_contains_description(self):
        exc = _make_rate_limit_exc("10 per hour")
        assert "10 per hour" in str(exc.detail)


class TestRateLimitedEndpointsExist:
    """Smoke-check that endpoints with @limiter.limit() are reachable (limiter bypassed in tests)."""

    async def test_auth_login_endpoint_responds(self, client):
        res = await client.post("/api/auth/login", json={
            "email": "no@example.com", "password": "wrongpassword",
        })
        assert res.status_code in (401, 422)

    async def test_auth_register_endpoint_responds(self, client):
        res = await client.post("/api/auth/register", json={
            "email": "x@x.com", "password": "short",
        })
        assert res.status_code in (200, 201, 400, 422)

    async def test_transactions_endpoint_requires_auth(self, client):
        res = await client.get("/api/transactions")
        assert res.status_code == 401

    async def test_alerts_endpoint_requires_auth(self, client):
        res = await client.get("/api/alerts")
        assert res.status_code == 401
