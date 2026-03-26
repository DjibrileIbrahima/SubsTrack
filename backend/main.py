from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth import router as auth_router
from routes.transactions import router as transactions_router

app = FastAPI(title="SubsTrack API", version="1.0.0")

# Allow React frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite's default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(transactions_router, prefix="/api", tags=["Transactions"])


@app.get("/")
async def root():
    return {"message": "SubsTrack API is running"}
