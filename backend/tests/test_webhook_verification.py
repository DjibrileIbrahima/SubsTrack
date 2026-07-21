"""
Direct unit tests for services/webhook_verification.py.

verify_plaid_webhook is mocked at the route level in test_webhooks.py. These
tests cover the function itself:

- a failure to fetch the JWK (e.g. Plaid's verification_keys endpoint 404ing
  for an unknown/rotated kid) is surfaced as a ValueError — not an unhandled
  httpx exception — so the route can turn it into a 400 instead of crashing
  with a 500.
- a 404 is retried once after a short delay, since it can mean the key was
  just rotated and hasn't propagated to Plaid's endpoint yet (seen right
  after linking, when a burst of webhooks like INITIAL_UPDATE fires).
"""

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

import services.webhook_verification as wv
from services.webhook_verification import verify_plaid_webhook

KID = "6c5516e1-92dc-479e-a8ff-5a51992e0001"
KEY_URL = "https://sandbox.plaid.com/webhook/v2/verification_keys/" + KID


@pytest.fixture(autouse=True)
def _clear_jwk_cache():
    wv._jwk_cache.clear()
    yield
    wv._jwk_cache.clear()


def _token_with_kid(kid: str) -> str:
    # Unverified header only needs to decode; the signature itself is never
    # checked in these tests since the key fetch fails first.
    return jwt.encode({"iat": 0}, "secret", algorithm="HS256", headers={"kid": kid})


def _valid_token_and_jwk(kid: str, body: bytes) -> tuple[str, str]:
    """A real ES256 keypair + a token Plaid-style signed with it, plus its JWK."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    algo = ECAlgorithm(ECAlgorithm.SHA256)
    jwk_str = algo.to_jwk(private_key.public_key())
    claims = {"iat": int(time.time()), "request_body_sha256": hashlib.sha256(body).hexdigest()}
    token = jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})
    return token, jwk_str


def _http_error_response(status_code: int):
    resp = MagicMock()
    request = httpx.Request("GET", KEY_URL)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} error", request=request, response=httpx.Response(status_code, request=request)
    )
    return resp


def _ok_response(text: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = text
    return resp


def _mock_client(get_side_effect):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=get_side_effect)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestFetchKeyFailure:
    async def test_persistent_404_raises_value_error_after_one_retry(self):
        token = _token_with_kid(KID)
        client = _mock_client([_http_error_response(404), _http_error_response(404)])

        with patch("services.webhook_verification.httpx.AsyncClient", return_value=client), \
             patch("services.webhook_verification.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError, match="verification key"):
                await verify_plaid_webhook(token, b"{}")

        assert client.get.await_count == 2
        mock_sleep.assert_awaited_once()

    async def test_transient_404_then_success_retries_and_verifies(self):
        body = b'{"webhook_type":"TRANSACTIONS","webhook_code":"INITIAL_UPDATE"}'
        token, jwk_str = _valid_token_and_jwk(KID, body)
        client = _mock_client([_http_error_response(404), _ok_response(jwk_str)])

        with patch("services.webhook_verification.httpx.AsyncClient", return_value=client), \
             patch("services.webhook_verification.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await verify_plaid_webhook(token, body)  # must not raise

        assert client.get.await_count == 2
        mock_sleep.assert_awaited_once()

    async def test_network_error_raises_value_error_without_retry(self):
        token = _token_with_kid(KID)
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("services.webhook_verification.httpx.AsyncClient", return_value=client):
            with pytest.raises(ValueError, match="verification key"):
                await verify_plaid_webhook(token, b"{}")

        assert client.get.await_count == 1

    async def test_missing_kid_raises_value_error(self):
        token = jwt.encode({"iat": 0}, "secret", algorithm="HS256")
        with pytest.raises(ValueError, match="kid"):
            await verify_plaid_webhook(token, b"{}")
