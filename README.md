# SubsTrack

A subscription tracker built with FastAPI, React, PostgreSQL, and Plaid.

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic
- **Frontend:** React + Vite + Recharts
- **Database:** PostgreSQL (Docker)
- **Cache / Rate limiting:** Redis (Docker)
- **Banking:** Plaid API (Sandbox)

## Project Structure
```
SubsTrack/
├── docker-compose.yml         # Production (all 4 containers)
├── docker-compose.dev.yml     # Development (DB + Redis)
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

## Security

The following controls are in place across the stack.

### Authentication & sessions
- Passwords hashed with **bcrypt**
- Auth stored in an **HttpOnly, SameSite=lax** cookie — never readable by JavaScript
- `COOKIE_SECURE` defaults to `true`; set it to `false` only in local dev (no HTTPS)
- JWT tokens signed with HS256; secret loaded from `JWT_SECRET` env var — app refuses to start if unset
- Google OAuth login protected against CSRF with a **cryptographically random `state` parameter** verified on callback
- OAuth-only accounts (no password) are explicitly rejected at the password-login endpoint

### Transport & headers
- nginx serves the following security headers on every response:
  - `X-Frame-Options: DENY` — blocks clickjacking
  - `X-Content-Type-Options: nosniff` — disables MIME sniffing
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy` — whitelists sources, blocks inline scripts and object embeds
  - `Permissions-Policy` — disables camera, microphone, and geolocation
  - `server_tokens off` — hides nginx version
- CORS restricted to origins in `CORS_ORIGINS` with an explicit header whitelist (`Content-Type`, `Authorization`, `X-Requested-With`)

### Data protection
- Plaid `access_token` values encrypted at rest with **Fernet** (AES-128-CBC + HMAC-SHA256); key loaded from `ENCRYPTION_KEY` env var — app refuses to start if unset
- Backend API port **not** exposed in Docker — all external traffic goes through nginx

### Rate limiting
- `POST /api/auth/login` — **10 requests/minute** per IP
- `POST /api/auth/register` — **5 requests/minute** per IP
- Enforced by **slowapi** backed by **Redis**, so limits are shared across all backend instances and survive restarts
- Exceeding the limit returns `429 Too Many Requests`
- `REDIS_URL` defaults to `redis://localhost:6379`; set to `redis://redis:6379` in production Docker (handled automatically by `docker-compose.yml`)

### Input validation
- All query parameters validated by FastAPI/Pydantic — e.g. `?days` clamped to 1–365
- Manual subscription fields validated: merchant length 1–100, amount > 0 and ≤ 100,000, category length ≤ 100
- 500 handlers return generic messages; full errors logged server-side only

### Secrets management
- `.env` is git-ignored; **never commit real secrets**
- `POSTGRES_PASSWORD` is required at compose startup — Docker will refuse to start if unset
- Generate the encryption key with:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- Generate a JWT secret with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

---

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
# Fill in your keys — see the Security section for generation commands
```

The following values are **required** — the app or Docker will refuse to start without them:
- `POSTGRES_PASSWORD` — database password
- `ENCRYPTION_KEY` — Fernet key for encrypting Plaid tokens
- `JWT_SECRET` — secret for signing auth tokens
- `PLAID_CLIENT_ID` / `PLAID_SECRET` — from your Plaid dashboard
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — from Google Cloud Console
- `REDIS_URL` — defaults to `redis://localhost:6379` (dev compose provides Redis automatically)

### 3. Start the database and Redis
```bash
# From root SubsTrack/ folder — starts PostgreSQL and Redis
docker compose -f docker-compose.dev.yml --env-file backend/.env up -d
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
