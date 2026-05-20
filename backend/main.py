import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limiter import limiter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from routes.auth import router as auth_router
from routes.transactions import router as transactions_router
from routes.alerts import router as alerts_router
from db.database import AsyncSessionLocal
from services.alert_service import generate_upcoming_alerts

logger = logging.getLogger(__name__)

app = FastAPI(title="SubsTrack API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

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

scheduler = AsyncIOScheduler()


async def _run_alert_job():
    async with AsyncSessionLocal() as db:
        try:
            await generate_upcoming_alerts(db)
        except Exception:
            logger.exception("Scheduled alert job failed")


@app.on_event("startup")
async def startup():
    scheduler.add_job(_run_alert_job, "interval", hours=24, id="alert_job")
    scheduler.start()
    logger.info("Alert scheduler started (runs every 24 h)")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/")
async def root():
    return {"message": "SubsTrack API is running"}