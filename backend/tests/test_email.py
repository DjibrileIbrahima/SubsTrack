"""
Direct unit tests for services/email.py.

send_reset_email and send_alert_email are always mocked at the route level in
other test files. These tests verify the functions themselves — correct
endpoint, payload structure, and failure handling — using a mocked HTTP client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services.email import _build_alert_email, send_alert_email, send_reset_email

ALERTS = [{"merchant": "Netflix", "amount": 15.99, "when": "Today"}]
TWO_ALERTS = [
    {"merchant": "Netflix", "amount": 15.99, "when": "Today"},
    {"merchant": "Spotify", "amount": 9.99, "when": "Tomorrow"},
]


def _mock_client(raise_for_status_effect=None):
    """Return a mock httpx.AsyncClient context manager."""
    resp = MagicMock()
    resp.json.return_value = {"id": "email-123"}
    if raise_for_status_effect:
        resp.raise_for_status.side_effect = raise_for_status_effect
    else:
        resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ─── send_reset_email ─────────────────────────────────────────────────────────

class TestSendResetEmail:
    async def test_returns_false_when_no_api_key(self):
        with patch("services.email.RESEND_API_KEY", ""):
            result = await send_reset_email("user@example.com", "http://localhost/?token=abc")
        assert result is False

    async def test_returns_true_on_success(self):
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=_mock_client()):
            result = await send_reset_email("user@example.com", "http://localhost/?token=abc")
        assert result is True

    async def test_posts_to_resend_endpoint(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_reset_email("user@example.com", "http://localhost/?token=abc")

        url = mock_client.post.call_args.args[0]
        assert url == "https://api.resend.com/emails"

    async def test_sends_correct_recipient_and_subject(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_reset_email("user@example.com", "http://localhost/?token=abc")

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["to"] == ["user@example.com"]
        assert "reset" in payload["subject"].lower()

    async def test_html_contains_reset_url(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_reset_email("user@example.com", "http://localhost/?token=my-token")

        payload = mock_client.post.call_args.kwargs["json"]
        assert "http://localhost/?token=my-token" in payload["html"]

    async def test_uses_bearer_auth_header(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "my-resend-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_reset_email("user@example.com", "http://localhost/?token=abc")

        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-resend-key"

    async def test_returns_false_on_http_error(self):
        exc = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=MagicMock(status_code=400, text="bad")
        )
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=_mock_client(raise_for_status_effect=exc)):
            result = await send_reset_email("user@example.com", "http://localhost/?token=abc")
        assert result is False

    async def test_returns_false_on_network_exception(self):
        mock_client = _mock_client()
        mock_client.post.side_effect = Exception("connection refused")
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            result = await send_reset_email("user@example.com", "http://localhost/?token=abc")
        assert result is False


# ─── send_alert_email ─────────────────────────────────────────────────────────

class TestSendAlertEmail:
    async def test_returns_false_when_no_api_key(self):
        with patch("services.email.RESEND_API_KEY", ""):
            result = await send_alert_email("user@example.com", ALERTS)
        assert result is False

    async def test_returns_true_on_success(self):
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=_mock_client()):
            result = await send_alert_email("user@example.com", ALERTS)
        assert result is True

    async def test_sends_correct_recipient(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_alert_email("user@example.com", ALERTS)

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["to"] == ["user@example.com"]

    async def test_subject_singular_for_one_alert(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_alert_email("user@example.com", ALERTS)

        subject = mock_client.post.call_args.kwargs["json"]["subject"]
        assert "1" in subject
        assert "charge" in subject.lower()
        assert subject.endswith("charge")  # singular, not "charges"

    async def test_subject_plural_for_multiple_alerts(self):
        mock_client = _mock_client()
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            await send_alert_email("user@example.com", TWO_ALERTS)

        subject = mock_client.post.call_args.kwargs["json"]["subject"]
        assert "2" in subject
        assert "charges" in subject.lower()

    async def test_returns_false_on_http_error(self):
        exc = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=MagicMock(status_code=400, text="bad")
        )
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=_mock_client(raise_for_status_effect=exc)):
            result = await send_alert_email("user@example.com", ALERTS)
        assert result is False

    async def test_returns_false_on_network_exception(self):
        mock_client = _mock_client()
        mock_client.post.side_effect = Exception("timeout")
        with patch("services.email.RESEND_API_KEY", "test-key"), \
             patch("services.email.httpx.AsyncClient", return_value=mock_client):
            result = await send_alert_email("user@example.com", ALERTS)
        assert result is False


# ─── _build_alert_email ───────────────────────────────────────────────────────

class TestBuildAlertEmail:
    def test_subject_is_singular_for_one_alert(self):
        subject, _ = _build_alert_email(ALERTS)
        assert "1 upcoming charge" in subject
        assert not subject.endswith("charges")

    def test_subject_is_plural_for_multiple_alerts(self):
        subject, _ = _build_alert_email(TWO_ALERTS)
        assert "2 upcoming charges" in subject

    def test_html_contains_merchant_name(self):
        _, html = _build_alert_email(ALERTS)
        assert "Netflix" in html

    def test_html_contains_formatted_amount(self):
        _, html = _build_alert_email(ALERTS)
        assert "15.99" in html

    def test_html_contains_when_label(self):
        _, html = _build_alert_email(ALERTS)
        assert "Today" in html

    def test_html_contains_all_merchants_for_multiple_alerts(self):
        _, html = _build_alert_email(TWO_ALERTS)
        assert "Netflix" in html
        assert "Spotify" in html
