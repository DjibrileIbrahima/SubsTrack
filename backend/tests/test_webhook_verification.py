"""
Direct unit tests for services/webhook_verification.py.

verify_plaid_webhook is mocked at the route level in test_webhooks.py. These
tests cover the function itself, in particular that a failure to fetch the
JWK (e.g. Plaid's verification_keys endpoint 404ing for an unknown/rotated
kid) is surfaced as a ValueError — not an unhandled httpx exception — so the
route can turn it into a 400 instead of crashing with a 500.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest

from services.webhook_verification import verify_plaid_webhook

KID = "6c5516e1-92dc-479e-a8ff-5a51992e0001"


def _token_with_kid(kid: str) -> str:
    # Unverified header only needs to decode; the signature itself is never
    # checked in these tests since the key fetch fails first.
    return jwt.encode({"iat": 0}, "secret", algorithm="HS256", headers={"kid": kid})


def _mock_client(*, status_code: int = 404):
    resp = MagicMock()
    request = httpx.Request("GET", "https://sandbox.plaid.com/webhook/v2/verification_keys/" + KID)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=request, response=httpx.Response(status_code, request=request)
    )

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestFetchKeyFailure:
    async def test_404_raises_value_error_not_http_error(self):
        token = _token_with_kid(KID)
        with patch("services.webhook_verification.httpx.AsyncClient", return_value=_mock_client(status_code=404)):
            with pytest.raises(ValueError, match="verification key"):
                await verify_plaid_webhook(token, b"{}")

    async def test_network_error_raises_value_error(self):
        token = _token_with_kid(KID)
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("services.webhook_verification.httpx.AsyncClient", return_value=client):
            with pytest.raises(ValueError, match="verification key"):
                await verify_plaid_webhook(token, b"{}")

    async def test_missing_kid_raises_value_error(self):
        token = jwt.encode({"iat": 0}, "secret", algorithm="HS256")
        with pytest.raises(ValueError, match="kid"):
            await verify_plaid_webhook(token, b"{}")
