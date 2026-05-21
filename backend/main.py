import os
import logging
from dotenv import load_dotenv

load_dotenv()  # must run before any local imports that read env vars at import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limiter import limiter
from routes.auth import router as auth_router
from routes.transactions import router as transactions_router
from routes.alerts import router as alerts_router

app = FastAPI(title="SubsTrack API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(transactions_router, prefix="/api", tags=["Transactions"])
app.include_router(alerts_router, prefix="/api", tags=["Alerts"])


@app.get("/")
async def root():
    return {"message": "SubsTrack API is running"}
