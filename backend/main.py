import logging
import os

from dotenv import load_dotenv

load_dotenv()  # must run before any local imports that read env vars at import time

from observability import configure_logging, init_sentry  # noqa: E402

configure_logging()
init_sentry()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from limiter import limiter  # noqa: E402
from middleware import CSRFOriginMiddleware, RequestLoggingMiddleware  # noqa: E402
from observability import init_otel  # noqa: E402
from routes.alerts import router as alerts_router  # noqa: E402
from routes.auth import router as auth_router  # noqa: E402
from routes.health import router as health_router  # noqa: E402
from routes.transactions import router as transactions_router  # noqa: E402
from routes.webhooks import router as webhooks_router  # noqa: E402

logger = logging.getLogger(__name__)

_docs_url = None if os.getenv("DISABLE_DOCS", "true").lower() == "true" else "/docs"
app = FastAPI(title="SubsTrack API", version="1.0.0", docs_url=_docs_url, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware — added last = outermost (runs first on incoming requests).
# Resulting order per request: RequestLogging -> CORS -> CSRF -> routes, so CSRF
# rejections are logged and carry CORS headers.
raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
app.add_middleware(CSRFOriginMiddleware, trusted_origins=set(allowed_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware)

# OpenTelemetry (instruments the app after it is created)
init_otel(app)

# Prometheus metrics at /metrics — protect this endpoint at the network level in production
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/health/ready", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("Prometheus /metrics endpoint enabled")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed; /metrics disabled")

# Routes
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(transactions_router, prefix="/api", tags=["Transactions"])
app.include_router(alerts_router, prefix="/api", tags=["Alerts"])
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])


@app.get("/")
async def root():
    return {"message": "SubsTrack API is running"}
