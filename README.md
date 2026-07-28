# SubsTrack

A subscription tracker built with FastAPI, React, PostgreSQL, and Plaid.

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic + ARQ
- **Frontend:** React + Vite + Recharts
- **Database:** PostgreSQL 16 (Docker)
- **Cache / Queue / Revocation:** Redis 7 (Docker, AOF persistence)
- **Banking:** Plaid API (Sandbox → Production)
- **Email alerts:** Resend API
- **Observability:** Sentry · Prometheus · OpenTelemetry · structured JSON logging — activation guide in [OBSERVABILITY.md](OBSERVABILITY.md)

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
│   │   ├── auth.py                 # Register, login (+lockout), refresh, MFA, OAuth, Plaid, profile, delete account
│   │   ├── transactions.py         # Subscriptions CRUD + sync
│   │   ├── alerts.py               # In-app alerts CRUD
│   │   ├── webhooks.py             # Plaid webhook receiver (signature-verified, arq-enqueued)
│   │   └── health.py               # /health, /health/ready
│   ├── services/
│   │   ├── encryption.py           # KMS (prod) / Fernet (dev) encryption for tokens + secrets
│   │   ├── jwt.py                  # Access + rotating refresh tokens (jti, typ claims)
│   │   ├── mfa.py                  # TOTP secret generation + verification
│   │   ├── subscription_detector.py
│   │   ├── subscription_pipeline.py
│   │   ├── subscription_sync.py
│   │   ├── transaction_store.py    # Local txn table + Plaid /transactions/sync cursor
│   │   ├── job_queue.py            # Shared arq enqueue helper (webhook + manual sync)
│   │   ├── alert_service.py
│   │   ├── email.py                # Resend integration
│   │   └── webhook_verification.py
│   ├── tests/                      # 466 tests, runs against in-memory SQLite
│   └── alembic/versions/
└── frontend/
    ├── nginx.conf
    └── src/
        ├── api/index.js
        ├── context/AuthContext.jsx
        ├── hooks/usePlaid.js
        ├── pages/
        │   ├── Dashboard.jsx
        │   ├── Settings.jsx        # Notifications, MFA, linked banks, delete account
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
- **Monthly spending chart** — bar chart of actual subscription charges over time, matched by merchant + amount + linked account so it tracks the same spend the stat cards project (not every dollar that left the account)
- **Category breakdown** — horizontal bar chart, monthly equivalent per category
- **Due Soon** — subscriptions renewing within 7 days, urgent highlighting for today/tomorrow
- **Manual subscriptions** — add, edit, and delete without a bank connection

### Subscriptions
- Plaid bank link to auto-detect recurring charges
- Subscription pipeline with confidence scoring and frequency inference (weekly / biweekly / monthly / quarterly / yearly)
- Source badge (Bank vs Manual) and detection metadata
- **Background sync** — the manual "Sync" button and Plaid webhooks both enqueue the same durable arq job per linked account instead of blocking the request; the frontend polls `GET /subscriptions/sync/status` for completion, so large accounts or multiple linked banks don't risk a gateway timeout

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
- Email/password registration and login (bcrypt, hashed off the event loop)
- Google OAuth 2.0
- **TOTP two-factor authentication** — Google Authenticator, Authy, or any TOTP app; enabled/disabled in Settings; also required to confirm account deletion
- Password reset via email token
- **Rotating sessions** — short-lived access token (30 min) plus a rotating refresh token (7 days) in HttpOnly cookies; the frontend refreshes transparently on a 401
- **Account deletion** — self-service from Settings; revokes every linked Plaid item, erases all data, and requires the password (plus a TOTP code when MFA is enabled)

---

## Security

### Authentication & sessions
- Passwords hashed with **bcrypt**, run in a worker thread so hashing never blocks the async event loop; verification is timing-equalised against a dummy hash to close the login enumeration oracle
- Auth stored in an **HttpOnly, Secure, SameSite=lax** cookie — unreadable by JavaScript
- **Short-lived access + rotating refresh tokens** — access tokens expire in 30 min; the refresh token (HttpOnly, scoped to `/api/auth`) rotates on every use. Redis tracks the single valid token per family, so replaying a superseded refresh token is treated as theft and revokes the whole session family
- JWT tokens carry a **`jti` (JWT ID)** claim unique to each login and a `typ` claim so access and refresh tokens can't be substituted for each other
- **JWT revocation** — logout writes `token_blocklist:{jti}` to Redis with TTL equal to the token's remaining lifetime; every authenticated request checks the blocklist before hitting the database, so a stolen token is invalidated the moment the user logs out. Password reset revokes all outstanding access *and* refresh tokens
- **Per-account login lockout** — after repeated failed attempts within a window, `POST /login` returns 429 for that account (keyed on the email, Redis-backed) — stops distributed brute force even when it stays under the per-IP limit
- **TOTP MFA** — secrets encrypted at rest before storage; QR code setup flow in Settings; two-step login when enabled; also gates account deletion
- Google OAuth protected against CSRF with a cryptographically random `state` parameter, and requires a Google-verified email
- OAuth-only accounts are explicitly rejected at the password-login endpoint

### API
- `/docs` and `/redoc` **disabled in production** (set `DISABLE_DOCS=false` in local `.env` to restore Swagger UI)
- `/metrics` not exposed externally — Prometheus scrape only
- Backend port not exposed in Docker — all traffic goes through nginx

### CSRF
- **Origin-check middleware** rejects (403) any state-changing request (POST/PUT/PATCH/DELETE) whose `Origin` header is present but not in the trusted `CORS_ORIGINS` set — a second layer behind `SameSite=lax`. Only fires when `Origin` is present, so non-browser clients and Plaid's server-to-server webhooks (excluded) are unaffected
- Google OAuth flow additionally guarded by a random `state` cookie

### Transport & headers
- nginx security headers on every response: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security` (HSTS), `Content-Security-Policy`, `Permissions-Policy`, `server_tokens off`
- **True client IP** derived from Cloudflare's `CF-Connecting-IP` and `X-Forwarded-For` **overwritten** (not appended) at nginx, so the rate limiter can't be defeated by a spoofed forwarding header
- CORS restricted to origins in `CORS_ORIGINS`
- Nginx upstream DNS resolved dynamically via Docker's embedded resolver — no 502s after backend restarts

### Data protection
- Plaid `access_token` values and TOTP secrets encrypted at rest. In production, **AWS KMS** performs the crypto server-side so the master key never touches the app host (`ENCRYPTION_KMS_KEY_ID`); for local dev, **Fernet / MultiFernet** (AES-128-CBC + HMAC-SHA256) with comma-separated `ENCRYPTION_KEYS` for rotation
- Ciphertexts are scheme-tagged, so KMS and legacy Fernet rows decrypt side by side — enabling a zero-downtime migration
- A Fernet key (`ENCRYPTION_KEY`/`ENCRYPTION_KEYS`) **or** `ENCRYPTION_KMS_KEY_ID`, plus `JWT_SECRET`, are required — the app refuses to start if none is set

### Plaid webhooks
- Incoming webhook JWTs verified (ES256, key pinned by `kid`, key-rotation retry) with a body-hash `compare_digest` check and an `iat` freshness window
- **Fail-closed** — an unsigned webhook is rejected (401) unless `PLAID_ALLOW_UNVERIFIED_WEBHOOKS=true` for local dev
- Rate-limited, and processed as durable **arq** jobs (de-duped per item) so a restart can't drop an update

### Rate limiting
| Endpoint | Limit |
|---|---|
| `POST /api/auth/register` | 5 req/min |
| `POST /api/auth/login` | 10 req/min (+ per-account lockout) |
| `POST /api/auth/refresh` | 60 req/min |
| `POST /api/auth/mfa/verify` | 10 req/min |
| `POST /api/auth/forgot-password` | 3 req/min |
| `POST /api/auth/reset-password` | 5 req/min |
| `POST /api/auth/delete-account` | 5 req/min |
| `POST /api/auth/link-token` | 20 req/min |
| `POST /api/auth/exchange-token` | 10 req/min |
| `POST /api/webhooks/plaid` | 120 req/min |

Enforced by **slowapi** backed by **Redis** — shared across instances, survives restarts. The per-IP limits are augmented by the per-account login lockout (see above), so a distributed attack rotating IPs is still throttled per target account.

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
| Request-ID correlation | Contextvar + log-record factory | Always on |
| Request logs + audit trail | `RequestLoggingMiddleware` | Always on |
| Slow query warnings | SQLAlchemy event listeners | `SLOW_QUERY_MS` (default 200 ms) |
| Exception tracking | Sentry | `SENTRY_DSN` |
| Metrics (HTTP, latency, errors) | Prometheus | Always on at `/metrics` |
| Distributed tracing | OpenTelemetry + OTLP | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Liveness / readiness | `/health`, `/health/ready` | Always on |

Every log line — not just the access log — carries the request's `request_id` (echoed to clients in the `X-Request-ID` header), plus the OpenTelemetry `trace_id` when tracing is active, so an error deep in a handler or service can be joined back to its request with one query. Audit events (auth, financial operations, account changes) are tagged `audit=true` in structured log output.

---

## CI/CD

Every push to `master` runs:

1. **Ruff** — Python linting
2. **Bandit** — Python security scan
3. **Pytest** — 466 backend tests (in-memory SQLite, mocked Redis + Plaid)
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
| `ENCRYPTION_KEY` | Fernet key for encrypting tokens (or `ENCRYPTION_KMS_KEY_ID` in production) |
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
| `JWT_EXPIRE_MINUTES` | `30` | Access-token lifetime (minutes) |
| `REFRESH_EXPIRE_DAYS` | `7` | Refresh-token / session lifetime (days) |
| `LOGIN_MAX_FAILS` | `10` | Failed logins before per-account lockout |
| `LOGIN_FAIL_WINDOW_SECONDS` | `900` | Lockout window (seconds) |
| `ENCRYPTION_KMS_KEY_ID` | — | AWS KMS key for prod encryption (else Fernet) |
| `ENCRYPTION_KEYS` | — | Comma-separated Fernet keys, newest first (rotation) |
| `PLAID_ALLOW_UNVERIFIED_WEBHOOKS` | `false` | Allow unsigned Plaid webhooks (local dev only) |
| `LOG_FORMAT` | — | Set `json` for structured logs |
| `SENTRY_DSN` | — | Sentry error tracking |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OpenTelemetry tracing |
| `SLOW_QUERY_MS` | `200` | Slow query warning threshold (ms) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | Postgres connection pool sizing (prod) |

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
# Backend (450 tests, no server needed)
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
- [x] Phase 9 — Production hardening (rotating refresh tokens, KMS-backed encryption, per-account login lockout, CSRF Origin middleware, spoof-proof rate-limit IPs, durable arq webhook queue, request-id log propagation, self-service account deletion)
- [ ] PostgreSQL backups to S3
- [ ] Docker resource limits
- [ ] Email verification on registration
- [ ] CSV export
