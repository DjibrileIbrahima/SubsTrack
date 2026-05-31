# SubsTrack

A subscription tracker built with FastAPI, React, PostgreSQL, and Plaid.

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic + ARQ
- **Frontend:** React + Vite + Recharts
- **Database:** PostgreSQL 16 (Docker)
- **Cache / Queue / Revocation:** Redis 7 (Docker, AOF persistence)
- **Banking:** Plaid API (Sandbox → Production)
- **Email alerts:** Resend API
- **Observability:** Sentry · Prometheus · OpenTelemetry · structured JSON logging

## Project Structure
```
SubsTrack/
├── dev.sh                          # One-command dev launcher
├── docker-compose.yml              # Production (all 5 containers)
├── docker-compose.dev.yml          # Development (DB + Redis only)
├── .github/workflows/test.yml      # CI/CD pipeline
├── backend/
│   ├── main.py                     # App factory, middleware wiring
│   ├── observability.py            # Logging, Sentry, OpenTelemetry setup
│   ├── middleware.py               # Request logging, audit events, latency
│   ├── limiter.py                  # slowapi rate limiter
│   ├── worker.py                   # ARQ WorkerSettings + alert cron job
│   ├── plaid_client.py
│   ├── requirements.txt
│   ├── db/
│   │   ├── database.py             # Engine + slow query detection
│   │   ├── models.py
│   │   └── deps.py                 # get_current_user, get_redis (JWT blocklist)
│   ├── routes/
│   │   ├── auth.py                 # Register, login, MFA, Google OAuth, Plaid, profile
│   │   ├── transactions.py         # Subscriptions CRUD + sync
│   │   ├── alerts.py               # In-app alerts CRUD
│   │   ├── webhooks.py             # Plaid webhook receiver
│   │   └── health.py               # /health, /health/ready
│   ├── services/
│   │   ├── encryption.py           # Fernet encryption for tokens + secrets
│   │   ├── jwt.py                  # JWT create/decode with jti claim
│   │   ├── mfa.py                  # TOTP secret generation + verification
│   │   ├── subscription_detector.py
│   │   ├── subscription_pipeline.py
│   │   ├── subscription_sync.py
│   │   ├── alert_service.py
│   │   ├── email.py                # Resend integration
│   │   └── webhook_verification.py
│   ├── tests/                      # 341 tests, runs against in-memory SQLite
│   └── alembic/versions/
└── frontend/
    ├── nginx.conf
    └── src/
        ├── api/index.js
        ├── context/AuthContext.jsx
        ├── hooks/usePlaid.js
        ├── pages/
        │   ├── Dashboard.jsx
        │   ├── Settings.jsx        # Notifications, MFA, linked banks
        │   └── auth/               # Login, Register, ForgotPassword, ResetPassword
        └── components/
            ├── Navbar.jsx          # Bell icon, unread badge, user menu
            ├── SubscriptionList.jsx
            ├── AddManualForm.jsx
            ├── SpendingChart.jsx
            └── CategoryChart.jsx
```

## Features

### Dashboard
- **Stat cards** — Monthly Spend, Annual Estimate (all frequencies), Subscription count
- **Monthly spending chart** — bar chart of transaction spend over time
- **Category breakdown** — horizontal bar chart, monthly equivalent per category
- **Due Soon** — subscriptions renewing within 7 days, urgent highlighting for today/tomorrow
- **Manual subscriptions** — add, edit, and delete without a bank connection

### Subscriptions
- Plaid bank link to auto-detect recurring charges
- Subscription pipeline with confidence scoring and frequency inference (weekly / biweekly / monthly / quarterly / yearly)
- Source badge (Bank vs Manual) and detection metadata

#### Detection pipeline details
- **Amount clustering** — multi-product merchants split into separate subscriptions by amount proximity
- **Calendar-aware renewal dates** — proper month arithmetic (Jan 31 + 1 month = Feb 28, not Mar 2)
- **Relative interval scoring** — drift thresholds scale with billing interval
- **Continuous frequency ranges** — no dead zones; 45-day average maps to quarterly
- **Word-boundary hint matching** — merchants like "Gaston Bistro" no longer falsely penalised by GAS filter
- **Rules-only fallback** — candidates above 0.65 confidence accepted without AI when no model is configured

### Alerts
- In-app alerts with unread badge in navbar
- Alerts generated daily via ARQ worker (Redis-backed, multi-instance safe) and on-demand via API
- Email alerts via Resend when subscriptions are due within 7 days
- Per-user opt-in for email and SMS alerts

### Auth
- Email/password registration and login (bcrypt)
- Google OAuth 2.0
- **TOTP two-factor authentication** — Google Authenticator, Authy, or any TOTP app; enabled/disabled in Settings
- Password reset via email token
- HttpOnly cookie sessions (7-day expiry)

---

## Security

### Authentication & sessions
- Passwords hashed with **bcrypt**
- Auth stored in an **HttpOnly, Secure, SameSite=lax** cookie — unreadable by JavaScript
- JWT tokens carry a **`jti` (JWT ID)** claim unique to each login
- **JWT revocation** — logout writes `token_blocklist:{jti}` to Redis with TTL equal to the token's remaining lifetime; every authenticated request checks the blocklist before hitting the database, so a stolen token is invalidated the moment the user logs out
- **TOTP MFA** — secrets encrypted at rest with Fernet before storage; QR code setup flow in Settings; two-step login when enabled
- Google OAuth protected against CSRF with a cryptographically random `state` parameter
- OAuth-only accounts are explicitly rejected at the password-login endpoint

### API
- `/docs` and `/redoc` **disabled in production** (set `DISABLE_DOCS=false` in local `.env` to restore Swagger UI)
- `/metrics` not exposed externally — Prometheus scrape only
- Backend port not exposed in Docker — all traffic goes through nginx

### Transport & headers
- nginx security headers on every response: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy`, `Permissions-Policy`, `server_tokens off`
- CORS restricted to origins in `CORS_ORIGINS`
- Nginx upstream DNS resolved dynamically via Docker's embedded resolver — no 502s after backend restarts

### Data protection
- Plaid `access_token` values and TOTP secrets encrypted at rest with **Fernet** (AES-128-CBC + HMAC-SHA256)
- `ENCRYPTION_KEY` and `JWT_SECRET` are required — the app refuses to start if unset

### Rate limiting
| Endpoint | Limit |
|---|---|
| `POST /api/auth/register` | 5 req/min |
| `POST /api/auth/login` | 10 req/min |
| `POST /api/auth/mfa/verify` | 10 req/min |
| `POST /api/auth/forgot-password` | 3 req/min |
| `POST /api/auth/link-token` | 20 req/min |
| `POST /api/auth/exchange-token` | 10 req/min |

Enforced by **slowapi** backed by **Redis** — shared across instances, survives restarts.

### Input validation
- All request bodies validated by Pydantic; query parameters clamped at route level
- 500 handlers return generic messages; full errors logged server-side only

### Secrets management
- `.env` is git-ignored; **never commit real secrets**
- `POSTGRES_PASSWORD` is required at compose startup — Docker refuses to start if unset
- Generate the encryption key:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- Generate a JWT secret:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

---

## Observability

| Signal | Tool | Activation |
|---|---|---|
| Structured JSON logs | Custom formatter | `LOG_FORMAT=json` |
| Request logs + audit trail | `RequestLoggingMiddleware` | Always on |
| Slow query warnings | SQLAlchemy event listeners | `SLOW_QUERY_MS` (default 200 ms) |
| Exception tracking | Sentry | `SENTRY_DSN` |
| Metrics (HTTP, latency, errors) | Prometheus | Always on at `/metrics` |
| Distributed tracing | OpenTelemetry + OTLP | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Liveness / readiness | `/health`, `/health/ready` | Always on |

Audit events (auth, financial operations, account changes) are tagged `audit=true` in structured log output.

---

## CI/CD

Every push to `master` runs:

1. **Ruff** — Python linting
2. **Bandit** — Python security scan
3. **Pytest** — 341 backend tests (in-memory SQLite, mocked Redis + Plaid)
4. **Vitest** — Frontend unit tests
5. **Vite build** — Production build verification
6. **SSH deploy** — Pull, rebuild containers, run Alembic migrations (only on `master` push, all jobs must pass)

---

## Local Development Setup

### 1. Clone the repo
```bash
git clone https://github.com/DjibrileIbrahima/SubsTrack.git
cd SubsTrack
```

### 2. Set up environment variables
```bash
cp backend/.env.example backend/.env
# Fill in the required values below
```

**Required** — app or Docker refuses to start without these:

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | Database password |
| `ENCRYPTION_KEY` | Fernet key for encrypting tokens |
| `JWT_SECRET` | Secret for signing auth tokens |
| `PLAID_CLIENT_ID` / `PLAID_SECRET` | From your Plaid dashboard |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |

**Optional:**

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `RESEND_API_KEY` | — | Email alerts |
| `ALERT_FROM_EMAIL` | — | Sender address for alert emails |
| `COOKIE_SECURE` | `true` | Set `false` for local dev without HTTPS |
| `DISABLE_DOCS` | `true` | Set `false` to enable Swagger UI |
| `LOG_FORMAT` | — | Set `json` for structured logs |
| `SENTRY_DSN` | — | Sentry error tracking |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OpenTelemetry tracing |
| `SLOW_QUERY_MS` | `200` | Slow query warning threshold (ms) |

### 3. Start everything
```bash
bash dev.sh
```

`dev.sh` handles the full startup sequence:
- Creates `.venv` if missing, installs `requirements.txt`
- Starts Docker containers (PostgreSQL + Redis)
- Waits for Postgres to be ready
- Starts FastAPI backend with hot reload
- Starts ARQ worker (cron jobs)
- Starts Vite frontend dev server
- `Ctrl+C` cleanly shuts everything down

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs *(set `DISABLE_DOCS=false`)* |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |

### Running tests
```bash
# Backend (341 tests, no server needed)
cd backend && pytest -v

# Frontend
cd frontend && npm test -- --run
```

---

## Troubleshooting

### PostgreSQL port conflict

**Symptom:** Backend starts but every request returns `500` with an auth error.

**Cause:** A local PostgreSQL is already on port 5432.

**Fix — option 1 (recommended):**
```powershell
Stop-Service postgresql*
Set-Service -Name postgresql* -StartupType Disabled
```

**Fix — option 2:** remap Docker to a free port in `docker-compose.dev.yml` and update `DATABASE_URL` accordingly.

### Stale backend or worker process

```powershell
taskkill /F /IM uvicorn.exe
taskkill /F /IM python.exe
```
Then restart with `bash dev.sh`.

### `RuntimeError: JWT_SECRET is not set` on startup

Always start via `bash dev.sh`, or `cd backend` first when running uvicorn manually — `load_dotenv()` needs to find `backend/.env` in the working directory.

---

## Plaid Sandbox Credentials
- **Username:** `user_good`
- **Password:** `pass_good`

---

## Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full guide — EC2, Docker, SSL, Cloudflare, Google OAuth, AWS Parameter Store, and ongoing maintenance.

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
- [x] Phase 6 — Dashboard Polish (annual spend, due-soon, category chart, empty states)
- [x] Phase 7 — Deployment (EC2, Docker Compose, CI/CD, Cloudflare, AWS Parameter Store)
- [x] Phase 8 — Security hardening (MFA/TOTP, JWT revocation, Redis AOF persistence, observability, /docs disabled)
- [ ] PostgreSQL backups to S3
- [ ] Docker resource limits
- [ ] Email verification on registration
- [ ] CSV export
