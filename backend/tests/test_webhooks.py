"""Tests for POST /api/webhooks/plaid."""

from unittest.mock import AsyncMock, patch

import pytest

VERIFY_PATH = "routes.webhooks.verify_plaid_webhook"
PLAID_ENV_PATH = "routes.webhooks.PLAID_ENV"


class TestWebhookBasics:
    async def test_valid_json_returns_200(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "DEFAULT_UPDATE",
            "item_id": "item-sandbox-abc123",
        })
        assert res.status_code == 200

    async def test_invalid_json_returns_400(self, client):
        res = await client.post(
            "/api/webhooks/plaid",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 400
        assert "Invalid JSON" in res.json()["detail"]

    async def test_response_contains_received_true(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "INITIAL_UPDATE",
            "item_id": "item-abc",
        })
        assert res.json()["received"] is True

    async def test_unknown_webhook_type_handled_gracefully(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "UNKNOWN_FUTURE_TYPE",
            "webhook_code": "SOME_CODE",
        })
        assert res.status_code == 200
        assert res.json()["received"] is True

    async def test_empty_body_handled_gracefully(self, client):
        res = await client.post("/api/webhooks/plaid", json={})
        assert res.status_code == 200


class TestTransactionsWebhook:
    @pytest.mark.parametrize("code", [
        "INITIAL_UPDATE",
        "HISTORICAL_UPDATE",
        "DEFAULT_UPDATE",
    ])
    async def test_supported_transaction_codes_acknowledged(self, client, code):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": code,
            "item_id": "item-abc123",
        })
        assert res.status_code == 200
        body = res.json()
        assert body["webhook_type"] == "TRANSACTIONS"
        assert body["webhook_code"] == code
        assert body["action"] == "acknowledged"

    async def test_transactions_removed_acknowledged(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "TRANSACTIONS_REMOVED",
            "item_id": "item-abc",
            "removed_transactions": ["txn-1", "txn-2"],
        })
        assert res.status_code == 200
        assert res.json()["action"] == "acknowledged"

    async def test_unknown_transaction_code_ignored(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "FUTURE_CODE",
            "item_id": "item-abc",
        })
        assert res.status_code == 200
        assert res.json()["action"] == "ignored"

    async def test_transactions_webhook_logs_info(self, client, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="routes.webhooks"):
            await client.post("/api/webhooks/plaid", json={
                "webhook_type": "TRANSACTIONS",
                "webhook_code": "DEFAULT_UPDATE",
                "item_id": "item-xyz",
            })
        assert "TRANSACTIONS" in caplog.text or "DEFAULT_UPDATE" in caplog.text

    async def test_missing_item_id_still_returns_200(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "DEFAULT_UPDATE",
        })
        assert res.status_code == 200


class TestItemWebhook:
    async def test_item_error_returns_error_code(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "ERROR",
            "item_id": "item-abc",
            "error": {
                "error_code": "ITEM_LOGIN_REQUIRED",
                "error_type": "ITEM_ERROR",
            },
        })
        assert res.status_code == 200
        body = res.json()
        assert body["webhook_code"] == "ERROR"
        assert body["error_code"] == "ITEM_LOGIN_REQUIRED"

    async def test_item_error_with_no_error_field_uses_unknown(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "ERROR",
            "item_id": "item-abc",
        })
        assert res.status_code == 200
        assert res.json()["error_code"] == "UNKNOWN"

    async def test_item_pending_expiration(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "PENDING_EXPIRATION",
            "item_id": "item-abc",
            "consent_expiration_time": "2026-06-01T00:00:00Z",
        })
        assert res.status_code == 200
        assert res.json()["webhook_code"] == "PENDING_EXPIRATION"

    async def test_user_permission_revoked(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "USER_PERMISSION_REVOKED",
            "item_id": "item-abc",
        })
        assert res.status_code == 200
        assert res.json()["webhook_code"] == "USER_PERMISSION_REVOKED"

    async def test_webhook_update_acknowledged(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "WEBHOOK_UPDATE_ACKNOWLEDGED",
            "item_id": "item-abc",
            "new_webhook_url": "https://example.com/webhook",
        })
        assert res.status_code == 200

    async def test_item_error_logs_at_error_level(self, client, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger="routes.webhooks"):
            await client.post("/api/webhooks/plaid", json={
                "webhook_type": "ITEM",
                "webhook_code": "ERROR",
                "item_id": "item-abc",
                "error": {"error_code": "ITEM_LOGIN_REQUIRED"},
            })
        assert "ERROR" in caplog.text or "ITEM_LOGIN_REQUIRED" in caplog.text

    async def test_unknown_item_code_handled(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "ITEM",
            "webhook_code": "SOME_FUTURE_CODE",
            "item_id": "item-abc",
        })
        assert res.status_code == 200


class TestWebhookSyncTrigger:
    """Verify that transaction update events enqueue a background sync."""

    @pytest.mark.parametrize("code", ["INITIAL_UPDATE", "HISTORICAL_UPDATE", "DEFAULT_UPDATE"])
    async def test_sync_enqueued_for_update_codes(self, client, code):
        with patch(
            "routes.webhooks.sync_subscriptions_for_item",
            new_callable=AsyncMock,
        ) as mock_sync:
            res = await client.post("/api/webhooks/plaid", json={
                "webhook_type": "TRANSACTIONS",
                "webhook_code": code,
                "item_id": "item-sandbox-abc",
            })
        assert res.status_code == 200
        mock_sync.assert_awaited_once_with("item-sandbox-abc")

    async def test_sync_not_enqueued_for_transactions_removed(self, client):
        with patch(
            "routes.webhooks.sync_subscriptions_for_item",
            new_callable=AsyncMock,
        ) as mock_sync:
            res = await client.post("/api/webhooks/plaid", json={
                "webhook_type": "TRANSACTIONS",
                "webhook_code": "TRANSACTIONS_REMOVED",
                "item_id": "item-sandbox-abc",
                "removed_transactions": ["txn-1"],
            })
        assert res.status_code == 200
        mock_sync.assert_not_awaited()

    async def test_sync_not_enqueued_when_item_id_missing(self, client):
        with patch(
            "routes.webhooks.sync_subscriptions_for_item",
            new_callable=AsyncMock,
        ) as mock_sync:
            res = await client.post("/api/webhooks/plaid", json={
                "webhook_type": "TRANSACTIONS",
                "webhook_code": "DEFAULT_UPDATE",
            })
        assert res.status_code == 200
        mock_sync.assert_not_awaited()

    async def test_sync_not_enqueued_for_item_webhooks(self, client):
        with patch(
            "routes.webhooks.sync_subscriptions_for_item",
            new_callable=AsyncMock,
        ) as mock_sync:
            res = await client.post("/api/webhooks/plaid", json={
                "webhook_type": "ITEM",
                "webhook_code": "ERROR",
                "item_id": "item-sandbox-abc",
                "error": {"error_code": "ITEM_LOGIN_REQUIRED"},
            })
        assert res.status_code == 200
        mock_sync.assert_not_awaited()


class TestWebhookSignatureVerification:
    """Verify the route enforces signature checks correctly."""

    async def test_valid_signature_passes(self, client):
        with patch(VERIFY_PATH, new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = None
            res = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE", "item_id": "item-abc"},
                headers={"Plaid-Verification": "valid.jwt.token"},
            )
        assert res.status_code == 200
        mock_verify.assert_awaited_once()

    async def test_invalid_signature_returns_400(self, client):
        with patch(VERIFY_PATH, new_callable=AsyncMock) as mock_verify:
            mock_verify.side_effect = ValueError("JWT signature verification failed")
            res = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE"},
                headers={"Plaid-Verification": "bad.jwt.token"},
            )
        assert res.status_code == 400
        assert "signature" in res.json()["detail"].lower()

    async def test_missing_header_in_sandbox_allowed(self, client):
        with patch(PLAID_ENV_PATH, "sandbox"):
            res = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE", "item_id": "item-abc"},
            )
        assert res.status_code == 200

    async def test_missing_header_in_production_returns_401(self, client):
        with patch(PLAID_ENV_PATH, "production"):
            res = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE", "item_id": "item-abc"},
            )
        assert res.status_code == 401
        assert "Plaid-Verification" in res.json()["detail"]

    async def test_verify_called_with_raw_body_and_token(self, client):
        payload = b'{"webhook_type":"ITEM","webhook_code":"ERROR","item_id":"item-abc"}'
        with patch(VERIFY_PATH, new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = None
            await client.post(
                "/api/webhooks/plaid",
                content=payload,
                headers={"Content-Type": "application/json", "Plaid-Verification": "my.jwt"},
            )
        mock_verify.assert_awaited_once_with("my.jwt", payload)


class TestWebhookCaseInsensitivity:
    async def test_lowercase_webhook_type_handled(self, client):
        """Webhook types should be normalised to uppercase."""
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "transactions",
            "webhook_code": "default_update",
            "item_id": "item-abc",
        })
        assert res.status_code == 200
        assert res.json()["received"] is True

    async def test_mixed_case_webhook_type(self, client):
        res = await client.post("/api/webhooks/plaid", json={
            "webhook_type": "Transactions",
            "webhook_code": "Default_Update",
            "item_id": "item-abc",
        })
        assert res.status_code == 200
