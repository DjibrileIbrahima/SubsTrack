"""
Tests for /api/auth/* routes.

Covers: register, login, logout, /me, Google OAuth flow,
Plaid link-token, token exchange, linked accounts,
forgot-password, and reset-password.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from db.models import LinkedAccount, PasswordResetToken, Subscription, User
from routes.auth import _hash_reset_token
from services.encryption import decrypt
from services.encryption import encrypt as _encrypt


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)

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

    async def test_register_stores_email_lowercased(self, client, db):
        r = await client.post("/api/auth/register", json={"email": "MixedCase@Example.COM", "password": "secure123"})
        assert r.status_code == 201
        assert r.json()["email"] == "mixedcase@example.com"
        result = await db.execute(select(User).where(User.email == "mixedcase@example.com"))
        assert result.scalar_one_or_none() is not None

    async def test_register_duplicate_email_different_case(self, client, test_user):
        """Foo@x.com and foo@x.com must be one account."""
        r = await client.post("/api/auth/register", json={"email": "TEST@Example.com", "password": "password123"})
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

    async def test_login_is_case_insensitive(self, client, test_user):
        r = await client.post("/api/auth/login", json={"email": "TEST@example.COM", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["email"] == "test@example.com"

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

    async def test_logout_blocklists_jti(self, auth_client, mock_redis_dep):
        """Logout must write the token's JTI to Redis so it cannot be reused."""
        r = await auth_client.post("/api/auth/logout")
        assert r.status_code == 200
        mock_redis_dep.setex.assert_called_once()
        key = mock_redis_dep.setex.call_args[0][0]
        assert key.startswith("token_blocklist:")

    async def test_revoked_token_is_rejected(self, auth_client, mock_redis_dep):
        """A token whose JTI is in Redis must be refused on every subsequent request."""
        mock_redis_dep.get.return_value = "1"  # simulate blocklisted token
        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 401
        assert "revoked" in r.json()["detail"].lower()


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


# ─── Session revocation (token_min_iat) ──────────────────────────────────────

class TestSessionRevocation:
    def _min_iat_getter(self, min_iat_value):
        """Redis .get stub: returns min_iat for revocation keys, None otherwise."""
        def _get(key):
            if key.startswith("token_min_iat:"):
                return str(min_iat_value)
            return None
        return _get

    async def test_reset_password_revokes_existing_sessions(
        self, client, db, test_user, mock_redis_dep
    ):
        token = "plain-reset-token-abc"
        db.add(PasswordResetToken(
            user_id=test_user.id,
            token=_hash_reset_token(token),
            expires_at=_utcnow() + timedelta(hours=1),
        ))
        await db.flush()

        r = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "newpassword123"},
        )
        assert r.status_code == 200
        revocation_keys = [
            c.args[0] for c in mock_redis_dep.setex.call_args_list
            if c.args[0].startswith("token_min_iat:")
        ]
        assert revocation_keys == [f"token_min_iat:{test_user.id}"]

    async def test_token_issued_before_revocation_is_rejected(
        self, auth_client, mock_redis_dep
    ):
        future = int(datetime.now(UTC).timestamp()) + 10
        mock_redis_dep.get.side_effect = self._min_iat_getter(future)

        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 401
        assert "revoked" in r.json()["detail"].lower()

    async def test_token_issued_after_revocation_is_accepted(
        self, auth_client, mock_redis_dep
    ):
        past = int(datetime.now(UTC).timestamp()) - 100
        mock_redis_dep.get.side_effect = self._min_iat_getter(past)

        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 200

    async def test_legacy_token_without_iat_fails_closed(
        self, client, test_user, mock_redis_dep
    ):
        """Pre-revocation-support tokens have no iat — must be rejected once
        a revocation marker exists."""
        import jwt as pyjwt

        from services.jwt import JWT_ALGORITHM, JWT_SECRET
        legacy = pyjwt.encode(
            {
                "sub": str(test_user.id),
                "exp": datetime.now(UTC) + timedelta(hours=1),
                "jti": str(uuid.uuid4()),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        client.cookies.set("access_token", legacy)
        past = int(datetime.now(UTC).timestamp()) - 100
        mock_redis_dep.get.side_effect = self._min_iat_getter(past)

        r = await client.get("/api/auth/me")
        assert r.status_code == 401


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
            {"email": "newgoogle@example.com", "verified_email": True},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        result = await db.execute(select(User).where(User.email == "newgoogle@example.com"))
        assert result.scalar_one_or_none() is not None

    async def test_callback_existing_user_gets_token(self, client, db, test_user):
        state = "valid-test-state-xyz"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": test_user.email, "verified_email": True},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        assert "access_token" in r.cookies

    async def test_callback_matches_existing_user_case_insensitively(self, client, db, test_user):
        """Google returning different casing must not create a second account."""
        state = "valid-test-state-case"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": "TEST@Example.com", "verified_email": True},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        result = await db.execute(select(User))
        users = result.scalars().all()
        assert len(users) == 1  # matched test_user, no new account
        assert users[0].id == test_user.id

    async def test_callback_rejects_unverified_email(self, client, db):
        """An unverified Google email must not log in or create an account."""
        state = "valid-test-state-unverified"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": "unverified@example.com", "verified_email": False},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code == 400
        assert "not verified" in r.json()["detail"]
        assert "access_token" not in r.cookies
        result = await db.execute(select(User).where(User.email == "unverified@example.com"))
        assert result.scalar_one_or_none() is None

    async def test_callback_rejects_missing_verified_email_claim(self, client, db):
        """Absence of the verified_email claim must fail closed."""
        state = "valid-test-state-noclaim"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": "noclaim@example.com"},
        )
        with patch("routes.auth.httpx.AsyncClient", return_value=mock_http):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code == 400
        assert "access_token" not in r.cookies

    async def test_callback_mfa_user_gets_no_session_cookie(self, client, db, test_user):
        """OAuth login must not bypass MFA — the user is handed off to /mfa/verify."""
        test_user.mfa_enabled = True
        test_user.mfa_secret = _encrypt("JBSWY3DPEHPK3PXP")
        await db.flush()

        state = "valid-test-state-mfa"
        client.cookies.set("oauth_state", state)

        mock_http = _make_httpx_mock(
            {"access_token": "google-token"},
            {"email": test_user.email, "verified_email": True},
        )
        mock_redis = AsyncMock()
        with (
            patch("routes.auth.httpx.AsyncClient", return_value=mock_http),
            patch("routes.auth._redis", return_value=mock_redis),
        ):
            r = await client.get(
                f"/api/auth/google/callback?code=authcode&state={state}",
                follow_redirects=False,
            )

        assert r.status_code in (302, 307)
        assert "access_token" not in r.cookies
        assert "mfa_token=" in r.headers["location"]
        # The MFA session must have been stored for /mfa/verify to pick up
        mock_redis.setex.assert_called_once()
        key = mock_redis.setex.call_args[0][0]
        assert key.startswith("mfa_session:")
        assert mock_redis.setex.call_args[0][2] == str(test_user.id)

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

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.link_token_create.return_value = mock_resp
            r = await auth_client.post("/api/auth/link-token")

        assert r.status_code == 200
        assert r.json()["link_token"] == "link-sandbox-test-token"

    async def test_create_link_token_unauthenticated(self, client):
        r = await client.post("/api/auth/link-token")
        assert r.status_code == 401

    async def test_create_link_token_plaid_error(self, auth_client):
        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.link_token_create.side_effect = Exception("Plaid API error")
            r = await auth_client.post("/api/auth/link-token")
        assert r.status_code == 500


# ─── POST /api/auth/link-token/update ────────────────────────────────────────

class TestUpdateLinkToken:
    async def test_update_link_token_for_own_account(self, auth_client, test_account):
        mock_resp = MagicMock()
        mock_resp.__getitem__ = lambda self, k: "link-update-token" if k == "link_token" else None

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.link_token_create.return_value = mock_resp
            r = await auth_client.post(
                "/api/auth/link-token/update",
                json={"account_id": str(test_account.id)},
            )

        assert r.status_code == 200
        assert r.json()["link_token"] == "link-update-token"

    async def test_update_link_token_unknown_account_returns_404(self, auth_client):
        r = await auth_client.post(
            "/api/auth/link-token/update",
            json={"account_id": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    async def test_update_link_token_other_users_account_returns_404(self, auth_client, test_user2, db):
        other_account = LinkedAccount(
            user_id=test_user2.id,
            access_token=_encrypt("other-token"),
            institution_name="Other Bank",
        )
        db.add(other_account)
        await db.flush()

        r = await auth_client.post(
            "/api/auth/link-token/update",
            json={"account_id": str(other_account.id)},
        )
        assert r.status_code == 404

    async def test_accounts_include_status(self, auth_client, test_account):
        r = await auth_client.get("/api/auth/accounts")
        assert r.status_code == 200
        assert r.json()["accounts"][0]["status"] == "active"


# ─── POST /api/auth/exchange-token ───────────────────────────────────────────

class TestExchangeToken:
    async def test_exchange_token_success(self, auth_client, db, test_user):
        exchange_resp = MagicMock()
        exchange_resp.__getitem__ = lambda self, k: "access-sandbox-abc" if k == "access_token" else "item-sandbox-abc"
        exchange_resp.get = lambda k, default=None: "access-sandbox-abc" if k == "access_token" else "item-sandbox-abc"

        with patch("services.plaid_service.client") as mock_plaid:
            mock_plaid.item_public_token_exchange.return_value = exchange_resp
            r = await auth_client.post(
                "/api/auth/exchange-token",
                json={"public_token": "public-sandbox-token", "institution_name": "Chase"},
            )

        assert r.status_code == 200
        assert "connected" in r.json()["message"].lower()

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
        with patch("services.plaid_service.client") as mock_plaid:
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


# ─── DELETE /api/auth/accounts/{id} ─────────────────────────────────────────

class TestUnlinkAccount:
    @pytest.fixture(autouse=True)
    def mock_item_remove(self):
        """Unlink revokes the item at Plaid — never call the real API in tests."""
        with patch("routes.auth.plaid_service.remove_item", new_callable=AsyncMock) as m:
            yield m

    async def test_unlink_success(self, auth_client, db, test_account):
        r = await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 200
        assert r.json()["message"] == "Account unlinked"

    async def test_unlink_revokes_item_at_plaid(self, auth_client, test_account, mock_item_remove):
        r = await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 200
        mock_item_remove.assert_awaited_once_with("access-sandbox-fake-token")

    async def test_plaid_failure_returns_502_and_keeps_account(
        self, auth_client, db, test_user, test_account, mock_item_remove
    ):
        """If Plaid revocation fails, nothing is deleted locally — retryable."""
        sub = Subscription(
            user_id=test_user.id, linked_account_id=test_account.id,
            merchant="Netflix", amount=15.99, frequency="monthly", source="plaid",
        )
        db.add(sub)
        await db.flush()

        mock_item_remove.side_effect = Exception("Plaid is down")
        r = await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 502

        result = await db.execute(select(LinkedAccount).where(LinkedAccount.id == test_account.id))
        assert result.scalar_one_or_none() is not None
        await db.refresh(sub)
        assert sub.is_active is True

    async def test_account_removed_from_db(self, auth_client, db, test_account):
        await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        result = await db.execute(select(LinkedAccount).where(LinkedAccount.id == test_account.id))
        assert result.scalar_one_or_none() is None

    async def test_plaid_subscriptions_soft_deleted(self, auth_client, db, test_user, test_account):
        sub = Subscription(
            user_id=test_user.id,
            merchant="Netflix",
            amount=15.99,
            frequency="monthly",
            source="plaid",
            is_active=True,
        )
        db.add(sub)
        await db.flush()

        await auth_client.delete(f"/api/auth/accounts/{test_account.id}")

        await db.refresh(sub)
        assert sub.is_active is False

    async def test_unlink_only_deactivates_that_banks_subscriptions(
        self, auth_client, db, test_user, test_account
    ):
        """Subscriptions from OTHER linked banks must survive an unlink."""
        second_account = LinkedAccount(
            user_id=test_user.id,
            access_token=_encrypt("access-sandbox-second-token"),
            item_id="item-sandbox-test-002",
            institution_name="Second Bank",
        )
        db.add(second_account)
        await db.flush()

        from_first = Subscription(
            user_id=test_user.id, linked_account_id=test_account.id,
            merchant="Netflix", amount=15.99, frequency="monthly", source="plaid",
        )
        from_second = Subscription(
            user_id=test_user.id, linked_account_id=second_account.id,
            merchant="Spotify", amount=9.99, frequency="monthly", source="plaid",
        )
        db.add(from_first)
        db.add(from_second)
        await db.flush()

        r = await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 200

        await db.refresh(from_first)
        await db.refresh(from_second)
        assert from_first.is_active is False
        assert from_second.is_active is True

    async def test_legacy_subs_survive_when_other_accounts_remain(
        self, auth_client, db, test_user, test_account
    ):
        """Unattributed (legacy) plaid subs are only swept on the LAST unlink."""
        second_account = LinkedAccount(
            user_id=test_user.id,
            access_token=_encrypt("access-sandbox-second-token"),
            item_id="item-sandbox-test-002",
            institution_name="Second Bank",
        )
        db.add(second_account)
        legacy = Subscription(
            user_id=test_user.id, linked_account_id=None,
            merchant="Hulu", amount=7.99, frequency="monthly", source="plaid",
        )
        db.add(legacy)
        await db.flush()

        r = await auth_client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 200

        await db.refresh(legacy)
        assert legacy.is_active is True  # Second Bank still linked — may be its sub

    async def test_manual_subscriptions_unaffected(self, auth_client, db, test_user, test_account):
        manual_sub = Subscription(
            user_id=test_user.id,
            merchant="Spotify",
            amount=9.99,
            frequency="monthly",
            source="manual",
            is_active=True,
        )
        db.add(manual_sub)
        await db.flush()

        await auth_client.delete(f"/api/auth/accounts/{test_account.id}")

        await db.refresh(manual_sub)
        assert manual_sub.is_active is True

    async def test_cannot_unlink_other_users_account(self, auth_client, db, test_user2):
        other_account = LinkedAccount(
            user_id=test_user2.id,
            access_token=_encrypt("other-token"),
            institution_name="Other Bank",
        )
        db.add(other_account)
        await db.flush()

        r = await auth_client.delete(f"/api/auth/accounts/{other_account.id}")
        assert r.status_code == 404

    async def test_nonexistent_account_returns_404(self, auth_client):
        r = await auth_client.delete(f"/api/auth/accounts/{uuid.uuid4()}")
        assert r.status_code == 404

    async def test_unauthenticated_returns_401(self, client, test_account):
        r = await client.delete(f"/api/auth/accounts/{test_account.id}")
        assert r.status_code == 401


# ─── POST /api/auth/forgot-password ──────────────────────────────────────────

class TestForgotPassword:
    async def test_known_user_triggers_email(self, client, test_user):
        with patch("routes.auth.send_reset_email", new_callable=AsyncMock) as mock_email:
            mock_email.return_value = True
            r = await client.post("/api/auth/forgot-password", json={"email": test_user.email})
        assert r.status_code == 200
        mock_email.assert_called_once()
        _, reset_url = mock_email.call_args.args
        assert "?token=" in reset_url

    async def test_unknown_email_returns_200_no_email(self, client):
        """Always 200 for unknown emails — prevents user enumeration."""
        with patch("routes.auth.send_reset_email", new_callable=AsyncMock) as mock_email:
            r = await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        assert r.status_code == 200
        mock_email.assert_not_called()

    async def test_oauth_only_user_returns_200_no_email(self, client, db):
        """OAuth users have no hashed_password — no reset email should be sent."""
        oauth_user = User(email="oauth@example.com", hashed_password=None)
        db.add(oauth_user)
        await db.flush()

        with patch("routes.auth.send_reset_email", new_callable=AsyncMock) as mock_email:
            r = await client.post("/api/auth/forgot-password", json={"email": "oauth@example.com"})
        assert r.status_code == 200
        mock_email.assert_not_called()

    async def test_creates_reset_token_in_db(self, client, test_user, db):
        with patch("routes.auth.send_reset_email", new_callable=AsyncMock) as mock_email:
            mock_email.return_value = True
            await client.post("/api/auth/forgot-password", json={"email": test_user.email})

        result = await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == test_user.id)
        )
        token_row = result.scalar_one_or_none()
        assert token_row is not None
        assert not token_row.used
        assert token_row.expires_at > _utcnow()

    async def test_invalid_email_format(self, client):
        r = await client.post("/api/auth/forgot-password", json={"email": "not-an-email"})
        assert r.status_code == 422


# ─── POST /api/auth/reset-password ───────────────────────────────────────────

class TestResetPassword:
    async def _seed_token(self, db, user_id, token="test-reset-token-xyz", *, expired=False, used=False):
        expires = (
            _utcnow() - timedelta(hours=1) if expired else _utcnow() + timedelta(hours=1)
        )
        reset = PasswordResetToken(user_id=user_id, token=_hash_reset_token(token), expires_at=expires, used=used)
        db.add(reset)
        await db.flush()
        return reset

    async def test_reset_success(self, client, test_user, db):
        await self._seed_token(db, test_user.id)
        r = await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "newpassword1"},
        )
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()

    async def test_new_password_allows_login(self, client, test_user, db):
        await self._seed_token(db, test_user.id)
        await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "brandnew123"},
        )
        r = await client.post("/api/auth/login", json={"email": test_user.email, "password": "brandnew123"})
        assert r.status_code == 200
        assert "access_token" in r.cookies

    async def test_token_marked_used_after_reset(self, client, test_user, db):
        reset = await self._seed_token(db, test_user.id)
        await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "newpassword1"},
        )
        await db.refresh(reset)
        assert reset.used is True

    async def test_reuse_token_rejected(self, client, test_user, db):
        await self._seed_token(db, test_user.id, used=True)
        r = await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "newpassword1"},
        )
        assert r.status_code == 400
        assert "invalid" in r.json()["detail"].lower() or "expired" in r.json()["detail"].lower()

    async def test_expired_token_rejected(self, client, test_user, db):
        await self._seed_token(db, test_user.id, expired=True)
        r = await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "newpassword1"},
        )
        assert r.status_code == 400

    async def test_invalid_token_rejected(self, client):
        r = await client.post(
            "/api/auth/reset-password",
            json={"token": "nonexistent-token-xyz", "password": "newpassword1"},
        )
        assert r.status_code == 400

    async def test_short_password_rejected(self, client, test_user, db):
        await self._seed_token(db, test_user.id)
        r = await client.post(
            "/api/auth/reset-password",
            json={"token": "test-reset-token-xyz", "password": "short"},
        )
        assert r.status_code == 400
        assert "8 characters" in r.json()["detail"]
