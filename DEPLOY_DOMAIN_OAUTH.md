# Domain, HTTPS + Google OAuth Setup Guide

How to put the app behind a custom domain (or subdomain) with HTTPS via
Cloudflare, and enable Google OAuth. Follow this after the app is already
running on EC2 (see DEPLOY_AWS.md).

This reflects the setup performed on 2026-07-14 for `substrack.sahelcom.com`.
Replace `app.yourdomain.com` / `yourdomain.com` with your names throughout.

**Order matters:** the Origin CA certificate must be installed on the server
(step 3) before the HTTPS nginx config is deployed — nginx exits at startup
if the cert files are missing.

---

## 1. Cloudflare — domain and DNS

### Add the domain
- [cloudflare.com](https://cloudflare.com) → **Add a domain** → enter `yourdomain.com` → **Free** plan
- At your registrar, replace the nameservers with the two Cloudflare provides
- Propagation takes minutes to ~24h; Cloudflare emails you when active

### Add the DNS record
A subdomain costs nothing — it's just a DNS record under a domain you own.

**DNS → Records → Add record**

| Field | Value |
|---|---|
| Type | `A` |
| Name | `app` (→ `app.yourdomain.com`) or `@` for the root |
| IPv4 address | Your EC2 Elastic IP |
| Proxy status | **Proxied** (orange cloud) |

---

## 2. Cloudflare — Origin CA certificate

Cloudflare's **Full (strict)** SSL mode requires a certificate the origin
(our nginx) presents to Cloudflare. The free Origin CA cert is valid 15 years
with no renewal automation needed. (Do NOT use "Flexible" — traffic between
Cloudflare and the origin would be unencrypted; this app carries financial
data. Plain "Full" is acceptable only as a stopgap.)

- Cloudflare → your domain → **SSL/TLS → Origin Server → Create Certificate**
- Defaults are fine: *Generate private key and CSR with Cloudflare*, **RSA (2048)**
- Hostnames: `yourdomain.com` and `*.yourdomain.com` (the wildcard covers any subdomain)
- Validity: **15 years** → **Create**
- The **Private Key is shown only once** — keep the page open until step 3 is done

---

## 3. Install the certificate on EC2

The cert lives OUTSIDE the repo checkout (`/opt/substrack` is a git working
tree — never keep private keys in it). docker-compose mounts this directory
read-only into the nginx container.

```bash
sudo mkdir -p /etc/ssl/substrack
sudo nano /etc/ssl/substrack/origin.crt   # paste the Origin Certificate block
sudo nano /etc/ssl/substrack/origin.key   # paste the Private Key block
sudo chmod 600 /etc/ssl/substrack/origin.key
```

Verify:

```bash
sudo openssl x509 -in /etc/ssl/substrack/origin.crt -noout -subject -enddate
sudo openssl rsa  -in /etc/ssl/substrack/origin.key -check -noout   # → "RSA key ok"
```

### Open port 443
EC2 console → instance **Security group → Edit inbound rules → Add rule**:
Type **HTTPS**, port **443**, source `0.0.0.0/0` (or restrict to
[Cloudflare's IP ranges](https://www.cloudflare.com/ips/) since all traffic
should arrive through the proxy).

The nginx 443 server block, compose port mapping, and cert mount are already
in the repo (`frontend/nginx.conf`, `docker-compose.yml`) — they deploy with
the next push. Port 80 just 301-redirects to HTTPS.

---

## 4. Parameter Store — all config lives in SSM, never in `.env`

**Do not hand-edit `/opt/substrack/backend/.env`** — `load-secrets.sh`
regenerates it from SSM Parameter Store on every deploy, wiping manual edits.

Set these (AWS console → **Systems Manager → Parameter Store**, or CLI):

```bash
aws ssm put-parameter --overwrite --name /substrack/FRONTEND_URL        --value "https://app.yourdomain.com" --type String
aws ssm put-parameter --overwrite --name /substrack/CORS_ORIGINS        --value "https://app.yourdomain.com" --type String
aws ssm put-parameter --overwrite --name /substrack/GOOGLE_REDIRECT_URI --value "https://app.yourdomain.com/api/auth/google/callback" --type String
aws ssm put-parameter --overwrite --name /substrack/COOKIE_SECURE       --value "true" --type String
aws ssm put-parameter --overwrite --name /substrack/PLAID_WEBHOOK_URL   --value "https://app.yourdomain.com/api/webhooks/plaid" --type String
```

`PLAID_WEBHOOK_URL` is what lets Plaid push ITEM/TRANSACTIONS webhooks
(instant "reconnect required" statuses instead of finding out on the next sync).

Then reload on the server:

```bash
sudo /opt/substrack/load-secrets.sh        # absolute path — works from any directory
cd /opt/substrack
sudo docker-compose up -d --force-recreate backend worker
```

---

## 5. Cloudflare — SSL mode

Only after the origin cert is installed and the 443 config is deployed:

- Cloudflare → **SSL/TLS → Overview** → **Full (strict)**

---

## 6. Google OAuth

### If an OAuth client already exists (e.g. from local dev)
- [console.cloud.google.com](https://console.cloud.google.com) → project → **APIs & Services → Credentials** → your OAuth 2.0 Client ID
- **Authorized JavaScript origins** → add `https://app.yourdomain.com`
- **Authorized redirect URIs** → add `https://app.yourdomain.com/api/auth/google/callback`
- **Save**. Keep (or re-add) the localhost entries alongside if you still develop locally — a client can hold multiple URIs.
- Client ID/secret are unchanged; nothing to reload server-side.

### If starting from scratch
- New project → **OAuth consent screen**: External, app name, your emails, authorized domain `yourdomain.com`
- **Credentials → Create Credentials → OAuth client ID** → Web application → add the origin + redirect URI above → **Create**
- Store the credentials in SSM and reload (step 4):

```bash
aws ssm put-parameter --overwrite --name /substrack/GOOGLE_CLIENT_ID     --value "<client id>"     --type String
aws ssm put-parameter --overwrite --name /substrack/GOOGLE_CLIENT_SECRET --value "<client secret>" --type SecureString
```

Notes:
- The console redirect URI must match SSM `GOOGLE_REDIRECT_URI` **exactly**
  (`https://`, no trailing slash).
- While the consent screen is in **Testing** status, only accounts listed
  under **Test users** can sign in — add your own email.
- Google can take a few minutes to propagate credential changes.

---

## 7. Verify + post-setup

- `https://app.yourdomain.com` loads with a padlock (the browser sees
  Cloudflare's edge cert; the Origin CA cert secures Cloudflare → origin)
- Email/password login works (`COOKIE_SECURE=true` requires HTTPS — now satisfied)
- **Continue with Google** completes and lands on the dashboard
- **One-time:** Settings → **Reconnect** each already-linked bank. The webhook
  URL only attaches to a Plaid item at Link time, so existing items need one
  update-mode pass to register `PLAID_WEBHOOK_URL`.

### Moving off the domain later
Re-point DNS, update the five SSM values + the Google console entries, reload
secrets, and reconnect banks once to re-register the webhook. (HSTS is
deliberately not sent by nginx so a temporary domain isn't pinned to HTTPS
after you repurpose it.)

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Cloudflare **521** | Can't reach origin :443 — security group not open, or frontend container down (`sudo docker-compose ps`) |
| Cloudflare **526** | Origin cert invalid — wrong files in `/etc/ssl/substrack`, or hostnames don't cover the (sub)domain |
| Redirect loop | Cloudflare SSL mode is "Flexible" — must be Full (strict) |
| `redirect_uri_mismatch` | Google console URI ≠ SSM `GOOGLE_REDIRECT_URI` — compare character-for-character |
| Google `access_denied` | Consent screen in Testing and your account isn't in Test users |
| Cookie not set after login | `COOKIE_SECURE=true` requires HTTPS end-to-end — check you're on `https://` |
| nginx container restart-looping | Cert files missing — nginx exits if `/etc/ssl/substrack/origin.{crt,key}` don't exist on the host |
| Settings changes don't survive deploys | You edited `.env` by hand — put the value in SSM instead (step 4) |
