# SubsTrack

A subscription tracker built with FastAPI, React, PostgreSQL, and Plaid.

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic + ARQ
- **Frontend:** React + Vite + Recharts
- **Database:** PostgreSQL (Docker)
- **Cache / Rate limiting:** Redis (Docker)
- **Banking:** Plaid API (Sandbox)
- **Email alerts:** Resend API

## Project Structure
```
SubsTrack/
├── dev.sh                         # One-command dev launcher (backend + worker + frontend)
├── docker-compose.yml             # Production (all containers)
├── docker-compose.dev.yml         # Development (DB + Redis only)
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── main.py
│   ├── plaid_client.py
│   ├── limiter.py                 # Shared slowapi/Redis rate limiter
│   ├── worker.py                  # ARQ WorkerSettings + cron job (alert generation)
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── .env.example
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── deps.py
│   ├── routes/
│   │   ├── auth.py                # Register, login, Google OAuth, Plaid link
│   │   ├── transactions.py        # Transactions, subscriptions, manual CRUD
│   │   └── alerts.py             # In-app alerts CRUD + manual trigger
│   ├── services/
│   │   ├── encryption.py          # Fernet encryption for Plaid tokens
│   │   ├── subscription_detector.py
│   │   ├── subscription_pipeline.py
│   │   ├── alert_service.py       # Alert generation + email dispatch
│   │   └── email.py              # Resend API integration
│   ├── tests/
│   │   ├── test_subscription_detector.py
│   │   └── test_alerts.sh
│   └── alembic/
│       ├── env.py
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
        ├── pages/
        │   ├── Dashboard.jsx
        │   ├── Login.jsx
        │   └── Register.jsx
        └── components/
            ├── Navbar.jsx          # Bell icon, unread alert badge, user menu
            ├── SubscriptionList.jsx
            ├── AddManualForm.jsx
            ├── SpendingChart.jsx   # Monthly bar chart
            └── CategoryChart.jsx   # Spend by category (horizontal bars)
```

## Features

### Dashboard
- **Stat cards** — Monthly Spend, Annual Estimate (all frequencies), Subscription count
- **Monthly spending chart** — bar chart of transaction spend over time
- **Category breakdown** — horizontal bar chart, monthly equivalent per category
- **Due Soon** — subscriptions renewing within 7 days, urgent highlighting for today/tomorrow
- **Manual subscriptions** — add, list, and delete without a bank connection

### Subscriptions
- Plaid bank link to auto-detect recurring charges
- Subscription pipeline with confidence scoring and frequency inference (weekly/biweekly/monthly/quarterly/yearly)
- Source badge (Bank vs Manual) and detection metadata

#### Detection pipeline details
- **Amount clustering** — multi-product merchants (e.g. Apple Music vs Apple TV+) are split into separate subscriptions based on amount proximity rather than grouped as one noisy entry
- **Calendar-aware renewal dates** — monthly/quarterly/yearly `next_expected` uses proper month arithmetic (Jan 31 + 1 month = Feb 28, not Mar 2)
- **Relative interval scoring** — consistency thresholds scale with the billing interval, so a ±2-day drift on a yearly subscription isn't penalised the same as on a weekly one
- **Continuous frequency ranges** — no dead zones; a 45-day average interval maps to quarterly rather than being discarded
- **Word-boundary hint matching** — merchants like "Gaston Bistro" or "Watercolor App" are no longer falsely penalised by the GAS/WATER non-subscription filter
- **Rules-only acceptance at 0.65** — when no AI model is configured, candidates above 0.65 confidence are accepted directly instead of being silently dropped

### Alerts
- In-app alerts with unread badge in navbar
- Alerts generated automatically daily via **ARQ** worker (Redis-backed, multi-instance safe) and on-demand via API
- Email alerts via Resend when subscriptions are due within 7 days
- Per-user opt-in for email alerts (`alert_email` preference)

### Auth
- Email/password registration and login (bcrypt)
- Google OAuth 2.0
- HttpOnly cookie sessions (7-day expiry)

---

## Security

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
- CORS restricted to origins in `CORS_ORIGINS` with an explicit header whitelist

### Data protection
- Plaid `access_token` values encrypted at rest with **Fernet** (AES-128-CBC + HMAC-SHA256); key loaded from `ENCRYPTION_KEY` env var — app refuses to start if unset
- Backend API port **not** exposed in Docker — all external traffic goes through nginx

### Rate limiting
| Endpoint | Limit |
|---|---|
| `POST /api/auth/register` | 5 req/min |
| `POST /api/auth/login` | 10 req/min |
| `POST /api/auth/link-token` | 20 req/min |
| `POST /api/auth/exchange-token` | 10 req/min |
| `POST /api/subscriptions/manual` | 30 req/min |
| `POST /api/alerts/generate` | 5 req/min |

Enforced by **slowapi** backed by **Redis** — limits are shared across instances and survive restarts.

### Input validation
- All query parameters validated by FastAPI/Pydantic — e.g. `?days` clamped to 1–365
- Manual subscription fields validated: merchant 1–100 chars, amount > 0 and ≤ 100,000, category ≤ 100 chars
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
cp backend/.env.example backend/.env
# Fill in your keys — see the Security section for generation commands
```

The following values are **required** — the app or Docker will refuse to start without them:

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | Database password |
| `ENCRYPTION_KEY` | Fernet key for encrypting Plaid tokens |
| `JWT_SECRET` | Secret for signing auth tokens |
| `PLAID_CLIENT_ID` / `PLAID_SECRET` | From your Plaid dashboard |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `REDIS_URL` | Defaults to `redis://localhost:6379` |

Optional:

| Variable | Description |
|---|---|
| `RESEND_API_KEY` | Resend API key for email alerts (alerts still work in-app without this) |
| `ALERT_FROM_EMAIL` | Sender address for alert emails (defaults to `alerts@yourdomain.com`) |
| `COOKIE_SECURE` | Set to `false` for local dev without HTTPS |

### 3. Start everything
```bash
bash dev.sh
```

`dev.sh` handles the full startup sequence automatically:
- Creates a Python virtual environment (`.venv`) if one doesn't exist
- Installs/syncs `backend/requirements.txt`
- Starts Docker containers (PostgreSQL + Redis)
- Waits for Postgres to be ready
- Starts the FastAPI backend with hot reload
- Starts the ARQ worker (runs cron jobs, purple `[worker]` log prefix)
- Starts the Vite frontend dev server
- `Ctrl+C` cleanly shuts down all three processes

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

### Running tests
```bash
# Unit tests (subscription detector — no server needed)
.venv/Scripts/python.exe -m pytest backend/tests/test_subscription_detector.py -v

# API smoke tests (requires running server)
bash backend/tests/test_alerts.sh
```

---

## Troubleshooting

### PostgreSQL port conflict

**Symptom:** Backend starts but every request returns `500`. Logs show:
```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "substrack"
```

**Cause:** A locally installed PostgreSQL is already on port 5432, intercepting the Docker container's connections.

**Fix — option 1 (recommended): disable the local service**
```powershell
Stop-Service postgresql*
Set-Service -Name postgresql* -StartupType Disabled
```

**Fix — option 2: remap Docker to a free port**

In `docker-compose.dev.yml`:
```yaml
ports:
  - "5434:5432"
```
And in `backend/.env`:
```
DATABASE_URL=postgresql+asyncpg://substrack:substrack_password@localhost:5434/substrack
```

### Stale backend or worker process

If the backend starts but Plaid calls fail with credential errors, a stale process from before `.env` was populated may still be running:
```powershell
taskkill /F /IM uvicorn.exe
taskkill /F /IM python.exe   # kills any lingering ARQ worker
```
Then restart with `bash dev.sh`.

### `RuntimeError: JWT_SECRET is not set` on startup

**Cause:** Running `uvicorn main:app` directly from a directory other than `backend/`, or from a shell that hasn't loaded `.env`. The app calls `load_dotenv()` before any imports, so it needs to find `backend/.env` in the working directory.

**Fix:** Always start via `bash dev.sh`, or `cd backend` first if running uvicorn manually.

---

## Plaid Sandbox Credentials
When testing with Plaid Link, use:
- **Username:** `user_good`
- **Password:** `pass_good`

---

## Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full guide covering server setup, SSL, Google OAuth configuration, environment variables, and ongoing maintenance.

```bash
docker compose up --build -d
```

---

## Roadmap
- [x] Phase 1 — Foundation (project structure, Docker, DB schema)
- [x] Phase 2 — Backend Core (auth, JWT, Plaid integration)
- [x] Phase 3 — Subscription Detection (pipeline, frequency inference, confidence scoring)
- [x] Phase 4 — React Frontend (dashboard, Plaid Link, manual subscriptions)
- [x] Phase 5 — Alerts (in-app alerts, email via Resend, scheduled jobs, navbar badge)
- [x] Phase 6 — Dashboard Polish (annual spend, due-soon section, category chart, empty states)
- [ ] Phase 7 — Deployment (production Docker, CI/CD)
- [ ] Phase 8 — Auth + Monetization
