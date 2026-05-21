# Production Deployment Guide

## 1. Provision a server
- A Linux VPS (DigitalOcean, Hetzner, AWS EC2, etc.) with **Docker** and **Docker Compose** installed
- Point your domain's DNS **A record** to the server IP

## 2. Clone the repo and set up environment
```bash
git clone https://github.com/YOUR_USERNAME/SubsTrack.git
cd SubsTrack
cp backend/.env.example backend/.env
# Fill in all production values — see table below
```

### Required `.env` changes for production

| Variable | What to set |
|---|---|
| `PLAID_ENV` | `sandbox` (keep for now) or `production` once Plaid-approved |
| `PLAID_SECRET` | Your Plaid secret for the chosen environment |
| `POSTGRES_PASSWORD` | Strong random password |
| `ENCRYPTION_KEY` | Fresh key — never reuse a dev key |
| `JWT_SECRET` | Fresh secret — never reuse a dev secret |
| `COOKIE_SECURE` | `true` |
| `CORS_ORIGINS` | `https://yourdomain.com` |
| `FRONTEND_URL` | `https://yourdomain.com` |
| `GOOGLE_REDIRECT_URI` | `https://yourdomain.com/api/auth/google/callback` |
| `RESEND_API_KEY` | Your Resend key |
| `ALERT_FROM_EMAIL` | A verified sender domain in Resend |

Generate secrets with:
```bash
# Encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT secret
python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Add SSL (HTTPS) — required before launch

The nginx container currently listens on port 80 only. Add HTTPS with one of these approaches:

**Option A — Cloudflare proxy (easiest):**
1. Add your domain to Cloudflare (free plan works)
2. Set DNS A record to your server IP with **Proxy** enabled (orange cloud)
3. In Cloudflare SSL/TLS settings, set mode to **Full (strict)**
4. Cloudflare handles HTTPS termination; nginx receives HTTP internally — no changes to `nginx.conf` needed

**Option B — Certbot on the host:**
1. Install Certbot: `sudo apt install certbot python3-certbot-nginx`
2. Update `frontend/nginx.conf` to add a port 443 server block and redirect 80 → 443
3. Mount the cert files into the frontend container via `docker-compose.yml`

## 4. Configure Google OAuth

> You do **not** need a separate Google account. Use your personal account and create a new **project** inside it.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project** → name it "SubsTrack"
3. In the new project, go to **APIs & Services → OAuth consent screen** — fill in app name, support email, and add your domain to authorized domains
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized JavaScript origins: `https://yourdomain.com`
   - Authorized redirect URIs: `https://yourdomain.com/api/auth/google/callback`
5. Copy the Client ID and Client Secret into `backend/.env`

## 5. Start everything
```bash
docker compose up --build -d
```

## 6. Run database migrations (first deploy only)
```bash
docker compose exec backend python -m alembic upgrade head
```

## 7. Verify
- Frontend loads at `https://yourdomain.com`
- API docs at `https://yourdomain.com/api/docs`
- Register an account, connect Plaid sandbox, sync subscriptions
- Check ARQ worker is running: `docker compose logs worker`

## What's already production-ready
- Security headers in nginx (X-Frame-Options, CSP, Referrer-Policy, etc.)
- HttpOnly + SameSite=lax auth cookies with `COOKIE_SECURE=true`
- Plaid access tokens encrypted at rest (Fernet AES-128)
- Backend port not exposed externally — all traffic through nginx
- Rate limiting shared across instances via Redis
- ARQ worker runs as a separate container, cron jobs are multi-instance safe
- `POSTGRES_PASSWORD` required at startup — Docker refuses to start without it

## CI / CD (GitHub Actions)

The workflow in `.github/workflows/test.yml` runs automatically on every push:

- **Tests** — runs `pytest` on every push and pull request
- **Deploy** — SSHs into the server and deploys only on push to `master`, and only if tests pass

### One-time setup: add GitHub secrets

Go to `github.com/YOUR_USERNAME/SubsTrack/settings/secrets/actions` → **New repository secret**:

| Secret | Value |
|---|---|
| `SERVER_IP` | Your VPS IP address |
| `SERVER_USER` | SSH username (e.g. `root` or `ubuntu`) |
| `SSH_PRIVATE_KEY` | Contents of your private key (`~/.ssh/id_rsa`) |

### One-time setup: prepare the server

Before the first automated deploy, clone the repo and place the `.env` on the server manually:

```bash
git clone https://github.com/YOUR_USERNAME/SubsTrack.git /opt/substrack
cp /opt/substrack/backend/.env.example /opt/substrack/backend/.env
# Fill in all production values
```

After that, every push to `master` that passes tests will automatically pull, rebuild containers, and run migrations.

## Ongoing maintenance

**Deploy an update:**
```bash
git pull
docker compose up --build -d
```

**Run migrations after a schema change:**
```bash
docker compose exec backend python -m alembic upgrade head
```

**View logs:**
```bash
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f frontend
```

**Restart a single service:**
```bash
docker compose restart backend
```
