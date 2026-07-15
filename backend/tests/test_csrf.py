"""Tests for the CSRF Origin-check middleware (middleware.CSRFOriginMiddleware).

The trusted origin in tests is the CORS_ORIGINS default, http://localhost:5173.
"""

TRUSTED_ORIGIN = "http://localhost:5173"
EVIL_ORIGIN = "http://evil.example.com"


class TestCsrfOriginCheck:
    async def test_state_changing_request_from_untrusted_origin_is_403(self, client):
        # Bad credentials would normally be 401; CSRF rejects before the handler.
        r = await client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "whatever"},
            headers={"Origin": EVIL_ORIGIN},
        )
        assert r.status_code == 403
        assert "cross-origin" in r.json()["detail"].lower()

    async def test_state_changing_request_from_trusted_origin_passes(self, client, test_user):
        # Trusted origin → CSRF lets it through; wrong password → 401 (not 403).
        r = await client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "wrongpass"},
            headers={"Origin": TRUSTED_ORIGIN},
        )
        assert r.status_code == 401

    async def test_request_without_origin_header_passes(self, client, test_user):
        # Non-browser clients omit Origin; they must not be blocked.
        r = await client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "wrongpass"},
        )
        assert r.status_code == 401

    async def test_safe_method_from_untrusted_origin_passes(self, client):
        # GET is not state-changing; CSRF must ignore it (auth still 401).
        r = await client.get("/api/auth/me", headers={"Origin": EVIL_ORIGIN})
        assert r.status_code == 401

    async def test_webhook_is_exempt_from_csrf(self, client):
        # Plaid posts server-to-server; the webhook path is excluded (and is
        # signature-verified instead). An Origin header must not block it.
        r = await client.post(
            "/api/webhooks/plaid",
            json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE", "item_id": "item-abc"},
            headers={"Origin": EVIL_ORIGIN},
        )
        assert r.status_code == 200

    async def test_authenticated_mutation_from_untrusted_origin_is_403(self, auth_client):
        # Even with a valid session cookie, a cross-origin mutation is rejected —
        # this is the CSRF attack shape.
        r = await auth_client.patch(
            "/api/auth/me",
            json={"alert_email": True},
            headers={"Origin": EVIL_ORIGIN},
        )
        assert r.status_code == 403

    async def test_null_origin_is_rejected(self, client, test_user):
        r = await client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "wrongpass"},
            headers={"Origin": "null"},
        )
        assert r.status_code == 403
