"""
Tests for /api/auth/* routes.

Covers: register, login, logout, /me, Google OAuth flow,
Plaid link-token, token exchange, and linked accounts.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import LinkedAccount, User
from services.encryption import decrypt
from services.encryption import encrypt as _encrypt

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _plaid_link_response():
    mock = MagicMock()
    mock.__getitem__ = lambda self, key: "link-sandbox-test-token" if key == "link_token" else None
    return mock


def _plaid_exchange_response():
    mock = MagicMock()
    mock.__getitem__ = lambda self, key: "access-sandbox-fake-token" if key == "access_token" else None
    return mock


def _make_httpx_mock(token_json, userinfo_json):
    """Builds a mock httpx.AsyncClient context manager for Google OAuth."""
    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = token_json

    userinfo_resp = MagicMock(status_code=200)
    userinfo_resp.json.return_value = userinfo_json

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=token_resp)
    mock_http.get = AsyncMock(return_value=userinfo_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    return mock_http


# ─── POST /api/auth/register ──────────────────────────────────────────────────

class TestRegister:
    async def test_register_success(self, client):
        r = await client.post("/api/auth/register", json={"email": "new@example.com", "password": "secure123"})
        assert r.status_code == 201
        assert r.json()["email"] == "new@example.com"
        assert "access_token" in r.cookies

    async def test_register_duplicate_email(self, client, test_user):
        r = await client.post("/api/auth/register", json={"email": "test@example.com", "password": "password123"})
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    async def test_register_short_password(self, client):
        r = await client.post("/api/auth/register", json={"email": "short@example.com", "password": "abc"})
        assert r.status_code == 400
        assert "8 characters" in r.json()["detail"]

    async def test_register_invalid_email(self, client):
        r = await client.post("/api/auth/register", json={"email": "not-an-email", "password": "password123"})
        assert r.status_code == 422  # Pydantic validation

    async def test_register_missing_fields(self, client):
        r = await client.post("/api/auth/register", json={"email": "x@y.com"})
        assert r.status_code == 422


# ─── POST /api/auth/login ─────────────────────────────────────────────────────

class TestLogin:
    async def test_login_success(self, client, test_user):
        r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["email"] == "test@example.com"
        assert "access_token" in r.cookies

    async def test_login_wrong_password(self, client, test_user):
        r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrongpass"})
        assert r.status_code == 401
        assert "Invalid" in r.json()["detail"]

    async def test_login_unknown_email(self, client):
        r = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password123"})
        assert r.status_code == 401

    async def test_login_google_only_user_no_password(self, client, db):
        """OAuth-only users have no hashed_password; password login must reject them."""
        google_user = User(email="googleonly@example.com", hashed_password=None)
        db.add(google_user)
        await db.flush()

        r = await client.post("/api/auth/login", json={"email": "googleonly@example.com", "password": "anything"})
        assert r.status_code == 401

    async def test_login_sets_httponly_cookie(self, client, test_user):
        r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
        assert r.status_code == 200
        cookie = r.cookies.get("access_token")
        assert cookie is not None


# ─── POST /api/auth/logout ────────────────────────────────────────────────────

class TestLogout:
    async def test_logout_clears_cookie(self, auth_client):
        r = await auth_client.post("/api/auth/logout")
        assert r.status_code == 200
        assert "Logged out" in r.json()["message"]

    async def test_logout_unauthenticated_still_succeeds(self, client):
        """Logout is idempotent — works even without an existing cookie."""
        r = await client.post("/api/auth/logout")
        assert r.status_code == 200


# ─── GET /api/auth/me ─────────────────────────────────────────────────────────

class TestGetMe:
    async def test_get_me_authenticated(self, auth_client, test_user):
        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == test_user.email
        assert "id" in data
        assert "alert_email" in data
        assert "alert_sms" in data

    async def test_get_me_unauthenticated(self, client):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401

    async def test_get_me_invalid_token(self, client):
        client.cookies.set("access_token", "not.a.real.token")
        r = await client.get("/api/auth/me")
        assert r.status_code == 401


# ─── PATCH /api/auth/me ───────────────────────────────────────────────────────

class TestUpdateMe:
    async def test_update_alert_email(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"alert_email": True})
        assert r.status_code == 200
        assert r.json()["alert_email"] is True

    async def test_update_alert_sms(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"alert_sms": True})
        assert r.status_code == 200
        assert r.json()["alert_sms"] is True

    async def test_update_phone(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"phone": "+15551234567"})
        assert r.status_code == 200
        assert r.json()["phone"] == "+15551234567"

    async def test_update_multiple_fields(self, auth_client):
        r = await auth_client.patch("/api/auth/me", json={"alert_email": True, "alert_sms": False})
        assert r.status_code == 200
        body = r.json()
        assert body["alert_email"] is True
        assert body["alert_sms"] is False

    async def test_update_me_unauthenticated(self, client):
        r = await client.patch("/api/auth/me", json={"alert_email": True})
        assert r.status_code == 401

    async def test_partial_update_does_not_reset_other_fields(self, auth_client, db, test_user):
        """PATCH only changes fields explicitly provided."""
        test_user.alert_email = True
        await db.flush()

        r = await auth_client.patch("/api/auth/me", json={"alert_sms": True})
        assert r.status_code == 200
        assert r.json()["alert_email"] is True  # unchanged
        assert r.json()["alert_sms"] is True


# ─── GET /api/auth/google ─────────────────────────────────────────────────────

class TestGoogleLogin:
    async def test_google_login_redirects(self, client):
        r = await client.get("/api/auth/google", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "accounts.google.com" in r.headers["location"]

    async def test_google_login_sets_state_cookie(self, client):
        r = await client.get("/api/auth/google", follow_redirects=False)
        assert "oauth_state" in r.cookies


# ─── GET /api/auth/google/callback ───────────────────────────────────────────

class TestGoogleCallback:
    async def test_callback_invalid_state(self, client):
        client.cookies.set("oauth_state", "correct-state")
        r = await client.get("/api/auth/google/callback?code=abc&state=WRONG", follow_redirects=False)
        assert r.status_code == 400
        assert "state" in r.json()["detail"].lower()

    async def test_callback_missing_state_cookie(self, client):
        r = await client.get("/api/auth/google/callback?code=abc&state=anything", follow_redirects=False)
        assert r.status_code == 400

    async def test_callback_creates_new_user(self, client, db):
        state = "valid-test-state-abc"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": "newgoogle@example.com"},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.email == "newgoogle@example.com"))
        assert result.scalar_one_or_none() is not None

    async def test_callback_existing_user_gets_token(self, client, db, test_user):
        state = "valid-test-state-xyz"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": test_user.email},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        assert "access_token" in r.cookies

    async def test_callback_google_token_error(self, client):
        state = "valid-test-state"
        client.cookies.set("oauth_state", state)

        bad_resp = MagicMock(status_code=400, text="bad_request")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=bad_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=bad&state={state}",
                follow_redirects=False,
            )

        assert r.status_code == 400


# ─── POST /api/auth/link-token ────────────────────────────────────────────────

class TestLinkToken:
    async def test_create_link_token(self, auth_client):
        mock_resp = MagicMock()
        mock_resp.__getitem__ = lambda self, k: "link-sandbox-test-token" if k == "link_token" else None

        with patch("routes.auth.client") as mock_plaid:
            mock_plaid.link_token_create.return_value = mock_resp
            r = await auth_client.post("/api/auth/link-token")

        assert r.status_code == 200
        assert r.json()["link_token"] == "link-sandbox-test-token"

    async def test_create_link_token_unauthenticated(self, client):
        r = await client.post("/api/auth/link-token")
        assert r.status_code == 401

    async def test_create_link_token_plaid_error(self, auth_client):
        with patch("routes.auth.client") as mock_plaid:
            mock_plaid.link_token_create.side_effect = Exception("Plaid API error")
            r = await auth_client.post("/api/auth/link-token")
        assert r.status_code == 500


# ─── POST /api/auth/exchange-token ───────────────────────────────────────────

class TestExchangeToken:
    async def test_exchange_token_success(self, auth_client, db, test_user):
        exchange_resp = MagicMock()
        exchange_resp.__getitem__ = lambda self, k: "access-sandbox-abc" if k == "access_token" else None

        with patch("routes.auth.client") as mock_plaid:
            mock_plaid.item_public_token_exchange.return_value = exchange_resp
            r = await auth_client.post(
                "/api/auth/exchange-token",
                json={"public_token": "public-sandbox-token", "institution_name": "Chase"},
            )

        assert r.status_code == 200
        assert "connected" in r.json()["message"].lower()

        from sqlalchemy import select
        result = await db.execute(select(LinkedAccount).where(LinkedAccount.user_id == test_user.id))
        account = result.scalar_one_or_none()
        assert account is not None
        assert account.institution_name == "Chase"
        # Token should be stored encrypted
        assert decrypt(account.access_token) == "access-sandbox-abc"

    async def test_exchange_token_unauthenticated(self, client):
        r = await client.post("/api/auth/exchange-token", json={"public_token": "tok"})
        assert r.status_code == 401

    async def test_exchange_token_plaid_error(self, auth_client):
        with patch("routes.auth.client") as mock_plaid:
            mock_plaid.item_public_token_exchange.side_effect = Exception("Exchange failed")
            r = await auth_client.post(
                "/api/auth/exchange-token",
                json={"public_token": "bad-token"},
            )
        assert r.status_code == 500


# ─── GET /api/auth/accounts ───────────────────────────────────────────────────

class TestGetAccounts:
    async def test_get_accounts_empty(self, auth_client):
        r = await auth_client.get("/api/auth/accounts")
        assert r.status_code == 200
        assert r.json()["accounts"] == []

    async def test_get_accounts_with_data(self, auth_client, test_account):
        r = await auth_client.get("/api/auth/accounts")
        assert r.status_code == 200
        accounts = r.json()["accounts"]
        assert len(accounts) == 1
        assert accounts[0]["institution"] == "Test Bank"

    async def test_get_accounts_only_own(self, auth_client, test_user2, db):
        """Users should only see their own linked accounts."""
        other_account = LinkedAccount(
            user_id=test_user2.id,
            access_token=_encrypt("other-token"),
            institution_name="Other Bank",
        )
        db.add(other_account)
        await db.flush()

        r = await auth_client.get("/api/auth/accounts")
        assert r.status_code == 200
        assert r.json()["accounts"] == []

    async def test_get_accounts_unauthenticated(self, client):
        r = await client.get("/api/auth/accounts")
        assert r.status_code == 401
