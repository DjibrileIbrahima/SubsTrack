import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("substrack.access")

# Paths that produce a structured audit record (login, bank ops, subscription writes)
_AUDIT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/exchange-token",
    "/api/auth/accounts",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/subscriptions",
    "/api/webhooks/plaid",
)

# Paths excluded from access logging entirely (health probes, static endpoints)
_SKIP_PREFIXES = ("/health", "/metrics", "/favicon.ico")

# Threshold (ms) above which a request is logged as slow
_SLOW_REQUEST_MS = 1000


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        status = response.status_code
        is_audit = any(request.url.path.startswith(p) for p in _AUDIT_PREFIXES)

        extra = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "duration_ms": duration_ms,
        }

        if is_audit:
            extra["audit"] = True

        if status >= 500:
            logger.error("request_error", extra=extra)
        elif duration_ms > _SLOW_REQUEST_MS:
            logger.warning("slow_request", extra=extra)
        elif is_audit:
            logger.info("audit_event", extra=extra)
        else:
            logger.info("request", extra=extra)

        response.headers["X-Request-ID"] = request_id
        return response
