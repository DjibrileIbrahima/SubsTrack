"""Tests for request-id log propagation (observability + middleware)."""

import json
import logging

from observability import _JsonFormatter, request_id_var


class TestRecordFactory:
    def test_record_carries_request_id_from_context(self):
        token = request_id_var.set("abc123")
        try:
            record = logging.getLogger("test.factory").makeRecord(
                "test.factory", logging.INFO, __file__, 1, "hello", None, None
            )
        finally:
            request_id_var.reset(token)
        assert record.request_id == "abc123"

    def test_json_formatter_emits_request_id(self):
        record = logging.getLogger("t").makeRecord(
            "t", logging.INFO, __file__, 1, "msg", None, None
        )
        record.request_id = "req-xyz"
        out = json.loads(_JsonFormatter().format(record))
        assert out["request_id"] == "req-xyz"
        # emitted once, not duplicated by the extra-field loop
        assert list(out.keys()).count("request_id") == 1


class TestRequestIdPropagation:
    async def test_application_logs_carry_request_id(self, client, caplog):
        """A log emitted INSIDE a route handler must carry the request's id —
        the whole point of the feature (access log already had it)."""
        with caplog.at_level(logging.INFO, logger="routes.webhooks"):
            r = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "FUTURE_CODE", "item_id": "x"},
                headers={"X-Request-ID": "testreqid123"},
            )
        assert r.headers["X-Request-ID"] == "testreqid123"
        handler_records = [rec for rec in caplog.records if rec.name == "routes.webhooks"]
        assert handler_records, "expected a routes.webhooks log during the request"
        assert all(getattr(rec, "request_id", None) == "testreqid123" for rec in handler_records)

    async def test_generated_request_id_is_used_when_header_absent(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="routes.webhooks"):
            r = await client.post(
                "/api/webhooks/plaid",
                json={"webhook_type": "TRANSACTIONS", "webhook_code": "FUTURE_CODE", "item_id": "x"},
            )
        rid = r.headers["X-Request-ID"]
        assert rid and rid != "-"
        rec = next(rec for rec in caplog.records if rec.name == "routes.webhooks")
        assert rec.request_id == rid
