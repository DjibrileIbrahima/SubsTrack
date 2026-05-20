# SubsTrack

A subscription tracker built with FastAPI, React, PostgreSQL, and Plaid.

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic
- **Frontend:** React + Vite + Recharts
- **Database:** PostgreSQL (Docker)
- **Banking:** Plaid API (Sandbox)

## Project Structure
```
SubsTrack/
├── docker-compose.yml         # Production (all 3 containers)
├── docker-compose.dev.yml     # Development (DB only)
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── main.py
│   ├── plaid_client.py
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── .env.example
│   ├── db/
│   │   ├── database.py
│   │   └── models.py
│   ├── routes/
│   │   ├── auth.py
│   │   └── transactions.py
│   ├── services/
│   │   ├── encryption.py
│   │   └── subscription_detector.py
│   └── alembic/
│       ├── env.py
│       ├── script.py.mako
│       └── versions/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── main.jsx
        ├── index.css
        ├── api/index.js
        ├── hooks/usePlaid.js
        ├── pages/Dashboard.jsx
        └── components/
            ├── Navbar.jsx
            ├── SubscriptionList.jsx
            ├── AddManualForm.jsx
            └── SpendingChart.jsx
```

## Local Development Setup

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/SubsTrack.git
cd SubsTrack
```

### 2. Set up environment variables
```bash
cd backend
cp .env.example .env
# Fill in your Plaid keys and generate an encryption key
```

Generate your encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Start the database
```bash
# From root SubsTrack/ folder
docker compose -f docker-compose.dev.yml up -d
```

### 4. Run backend
```bash
cd backend
pip install -r requirements.txt
alembic revision --autogenerate -m "initial tables"
alembic upgrade head
uvicorn main:app --reload
```
API runs at http://localhost:8000
API docs at http://localhost:8000/docs

### 5. Run frontend
```bash
cd frontend
npm install
npm run dev
```
App runs at http://localhost:5173

## Troubleshooting

### PostgreSQL port conflict (`password authentication failed` or connection refused)

**Symptom:** The backend starts but every API request returns `500 Internal Server Error`. The logs show:
```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "substrack"
```
or
```
asyncpg.exceptions.ConnectionRefusedError: connection refused
```

**Cause:** A locally installed PostgreSQL service is already listening on port 5432 (and sometimes 5433 as well). When the backend connects to `localhost:5432`, the OS routes the connection to the local Postgres rather than the Docker container, and the `substrack` user does not exist there.

**How to confirm:**
```bash
# Windows — shows PIDs on port 5432
netstat -ano | findstr ":5432"

# Then check the owning process
tasklist /FI "PID eq <pid>"
```
If you see a `postgres.exe` process that is *not* `com.docker.backend`, a local installation is conflicting.

**Fix — option 1 (recommended): disable the local Postgres service**
```powershell
# Stop the service and prevent it starting at boot
Stop-Service postgresql*
Set-Service -Name postgresql* -StartupType Disabled
```
Then restart the Docker DB container and the backend — port 5432 is now exclusively owned by Docker.

**Fix — option 2: remap Docker to a free port**

Find a free port (e.g. 5434):
```bash
netstat -ano | findstr ":5434"   # should return nothing
```
Then edit `docker-compose.dev.yml`:
```yaml
ports:
  - "5434:5432"
```
And update `DATABASE_URL` in `backend/.env`:
```
DATABASE_URL=postgresql+asyncpg://substrack:substrack_password@localhost:5434/substrack
```

---

## Plaid Sandbox Credentials
When testing with Plaid Link, use:
- **Username:** `user_good`
- **Password:** `pass_good`

## Production Deployment
```bash
# Build and run all 3 containers
docker compose up --build
```

## Roadmap
- [x] Phase 1 — Foundation
- [x] Phase 2 — Backend Core
- [x] Phase 3 — Plaid Integration
- [x] Phase 4 — React Frontend
- [ ] Phase 5 — Alerts (in-app, email, SMS)
- [ ] Phase 6 — Polish + AI features
- [ ] Phase 7 — Deployment
- [ ] Phase 8 — Auth + Monetization
