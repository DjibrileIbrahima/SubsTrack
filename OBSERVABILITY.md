# Observability Runbook

The app is heavily instrumented (structured logging, Sentry SDK, Prometheus
`/metrics`, OpenTelemetry tracing, request IDs, slow-query/slow-request
detection) — but every layer is **dormant until configured**. Out of the box,
everything goes to container stdout on the EC2 box, which means SSH + grep
to debug anything. This runbook activates each layer, cheapest first.

State legend: ✅ active once you follow the section · 🔧 requires a small
code/compose change (marked below).

---

## Current wiring (what the code already does)

| Layer | Where | Trigger |
|---|---|---|
| JSON log formatter | `backend/observability.py` | `LOG_FORMAT=json` |
| Request logs, request IDs, audit events, slow requests (>1s) | `backend/middleware.py` | always on |
| Slow query warnings (>200ms) | `backend/db/database.py` | always on (`SLOW_QUERY_MS` to tune) |
| Sentry: FastAPI + SQLAlchemy + ARQ + all `logger.exception`/ERROR logs | `backend/observability.py` | `SENTRY_DSN` set |
| Prometheus metrics at `/metrics` | `backend/main.py` | always exposed, nothing scrapes it |
| OpenTelemetry traces (OTLP export) | `backend/observability.py` | `OTEL_EXPORTER_OTLP_ENDPOINT` set |
| Worker job telemetry (`job_start`/`job_complete`/`job_failed`) | `backend/worker.py` | always on |
| `/health` and `/health/ready` endpoints | `backend/routes/health.py` | always on, nothing pings them |

All configuration goes through **SSM Parameter Store** (never hand-edit
`.env` — `load-secrets.sh` regenerates it on every deploy; see
DEPLOY_DOMAIN_OAUTH.md §4).

---

## Tier 1 — error tracking + uptime (~20 min, no code changes)

### Sentry
Every 500, failed webhook sync, and worker job failure already calls
`logger.exception`, which Sentry's LoggingIntegration captures as an alerting,
deduplicated event with full traceback and request context. It just needs a DSN.

1. Create a free project at [sentry.io](https://sentry.io) (platform: FastAPI)
   and copy the DSN.
2. ```bash
   aws ssm put-parameter --overwrite --name /substrack/SENTRY_DSN --value "<dsn>" --type SecureString
   aws ssm put-parameter --overwrite --name /substrack/ENV        --value "production" --type String
   aws ssm put-parameter --overwrite --name /substrack/LOG_FORMAT --value "json" --type String
   ```
3. Reload on the server:
   ```bash
   sudo /opt/substrack/load-secrets.sh
   cd /opt/substrack && sudo docker-compose up -d --force-recreate backend worker
   ```
4. Verify: the backend logs `Sentry initialized` on startup
   (`sudo docker-compose logs backend | grep -i sentry`). Trigger any error
   (e.g. a 404→500 path or a bad sync) and confirm an event appears in Sentry.

Notes:
- `send_default_pii=False` is already set — user emails/IPs are not sent.
- `SENTRY_TRACES_SAMPLE_RATE` (default 0.1) controls performance tracing volume.

### Uptime monitoring
Point [UptimeRobot](https://uptimerobot.com) (free) at:
```
https://substrack.sahelcom.com/health
```
5-minute interval, alert to your email. Now you learn the site is down before
you happen to visit it. `/health/ready` also checks DB/Redis if you want a
deeper probe (slightly more load).

---

## Tier 2 — logs off the box: CloudWatch Logs 🔧

Replaces SSH + `docker-compose logs | grep` with searchable, retained logs in
the AWS console. Two parts:

### 1. IAM permission (one-time)
Attach to the EC2 instance role (the same role that has `ssm:GetParametersByPath`):

```json
{
  "Effect": "Allow",
  "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
  "Resource": "arn:aws:logs:*:*:log-group:/substrack/*"
}
```

### 2. docker-compose logging driver (code change — not yet applied)
Add to the `backend` and `worker` services in `docker-compose.yml`:

```yaml
    logging:
      driver: awslogs
      options:
        awslogs-region: us-east-1
        awslogs-group: /substrack/backend        # /substrack/worker for the worker
        awslogs-create-group: "true"
```

With `LOG_FORMAT=json` (Tier 1), CloudWatch Logs Insights can then query
structured fields directly, e.g. all slow requests:

```
fields ts, msg, path, duration_ms
| filter msg = "slow_request"
| sort duration_ms desc
```

or everything for one request ID (the `X-Request-ID` response header):

```
fields ts, level, logger, msg | filter request_id = "abc123def456"
```

Caveat: `docker-compose logs` on the box stops working for services using the
awslogs driver — the console/CLI becomes the place to read logs (that's the
point).

---

## Tier 3 — metrics + traces: Grafana Cloud (free tier)

Lights up the two dormant layers with env vars only:

- **Metrics:** `/metrics` already exposes request rates/latencies per route.
  Configure Grafana Alloy (or any Prometheus agent) on the EC2 box to scrape
  `backend:8000/metrics` and remote-write to Grafana Cloud. Keep `/metrics`
  unexposed publicly (it is only reachable on the compose network today —
  keep it that way).
- **Traces:** set the OTLP endpoint and the existing wiring does the rest:
  ```bash
  aws ssm put-parameter --overwrite --name /substrack/OTEL_EXPORTER_OTLP_ENDPOINT --value "<grafana otlp endpoint>" --type String
  aws ssm put-parameter --overwrite --name /substrack/OTEL_SERVICE_NAME --value "substrack-backend" --type String
  ```
  then reload secrets + recreate. Every request gets a distributed trace
  (FastAPI auto-instrumented).

Worth building once dashboards exist: request latency by route, 5xx rate,
sync duration, Plaid failure rate, alert-job outcomes.

---

## Recommended code improvement (open TODO) 🔧

Plaid failures log raw tracebacks, but the **`error_code`** (the single most
diagnostic string — see the 2026-07-14 incidents) is not attached as a
structured field. Where `ApiException` is caught/logged, add:

```python
logger.exception("...", extra={"plaid_error_code": plaid_error_code(exc)})
```

so Sentry groups by code and CloudWatch can `filter plaid_error_code = "ITEM_LOGIN_REQUIRED"`.

---

## Where to look when something breaks

| Symptom | First stop |
|---|---|
| Users report errors / 500s | **Sentry** — the event has traceback + request context |
| Site unreachable | **UptimeRobot** alert → Cloudflare status codes (521/526 = origin; see DEPLOY_DOMAIN_OAUTH.md troubleshooting) |
| "It's slow" | CloudWatch Insights `slow_request` / `slow_query` queries; Grafana latency dashboards |
| Sync/webhook misbehavior without a 500 | CloudWatch: filter `logger = "services.subscription_sync"` or the item ID |
| Deploy failed | GitHub Actions run (Deploy job) — see also the gh CLI notes in the repo memory |
| Worker/cron issues | Sentry (job_failed is ERROR-level) or CloudWatch `/substrack/worker` |

Until Tiers 1–2 are done, the fallback remains SSH:
`cd /opt/substrack && sudo docker-compose logs backend --tail 200 | grep -iB5 -A40 "<term>"`.
