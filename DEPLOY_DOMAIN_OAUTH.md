# Domain + Google OAuth Setup Guide

This guide covers adding a custom domain with HTTPS via Cloudflare and enabling Google OAuth.
Follow this after the app is already running on EC2 (see DEPLOY_AWS.md).

---

## 1. Buy a Domain

Recommended registrars (cheapest):
- [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) — at-cost pricing, no markup (~$8-10/year for .com)
- [Namecheap](https://www.namecheap.com) — often has .com for $8-10/year

---

## 2. Set up Cloudflare

### Create a Cloudflare account
- Go to [cloudflare.com](https://cloudflare.com) → Sign up (free plan is fine)

### Add your domain
- Click **Add a domain** → enter your domain (e.g. `substrack.com`)
- Select the **Free** plan
- Cloudflare will scan existing DNS records → review and continue

### Update nameservers at your registrar
Cloudflare will give you two nameservers like:
```
aria.ns.cloudflare.com
bob.ns.cloudflare.com
```
Go to your registrar (wherever you bought the domain) → find **DNS** or **Nameservers** settings → replace existing nameservers with the two Cloudflare ones.

Propagation takes a few minutes to 24 hours. Cloudflare will email you when active.

### Add DNS A record
Once your domain is active in Cloudflare:
- **DNS → Records → Add record**

| Field | Value |
|---|---|
| Type | `A` |
| Name | `@` |
| IPv4 address | Your EC2 Elastic IP |
| Proxy status | **Proxied** (orange cloud) |

Optionally add `www` too:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `www` |
| IPv4 address | Your EC2 Elastic IP |
| Proxy status | **Proxied** (orange cloud) |

### Set SSL mode
- Cloudflare → **SSL/TLS → Overview**
- Select **Full (strict)**

This gives you free HTTPS with no Certbot or cert renewals needed. Cloudflare handles it all.

---

## 3. Update the backend `.env` on the server

SSH into your EC2 instance and edit the `.env`:

```bash
nano /opt/substrack/backend/.env
```

Update these values:

```env
FRONTEND_URL=https://yourdomain.com
CORS_ORIGINS=https://yourdomain.com
COOKIE_SECURE=true
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback
```

---

## 4. Set up Google OAuth

### Create a Google Cloud project
- Go to [console.cloud.google.com](https://console.cloud.google.com)
- Use your **personal Google account** — no need to create a separate one
- Click the project dropdown at the top → **New Project**
- Name it `SubsTrack` → **Create**

### Configure OAuth consent screen
- Left sidebar → **APIs & Services → OAuth consent screen**
- User type: **External** → **Create**
- Fill in:
  - App name: `SubsTrack`
  - User support email: your email
  - Developer contact email: your email
  - Authorized domains: `yourdomain.com`
- Click through the rest with defaults → **Save and Continue** until done

### Create OAuth credentials
- Left sidebar → **Credentials → Create Credentials → OAuth 2.0 Client ID**
- Application type: **Web application**
- Name: `SubsTrack`
- Under **Authorized JavaScript origins** → Add:
  ```
  https://yourdomain.com
  ```
- Under **Authorized redirect URIs** → Add:
  ```
  https://yourdomain.com/api/auth/google/callback
  ```
- Click **Create**

### Copy credentials into `.env`
A popup will show your **Client ID** and **Client Secret**. Add them to the `.env` on the server:

```env
GOOGLE_CLIENT_ID=your_actual_client_id
GOOGLE_CLIENT_SECRET=your_actual_client_secret
```

---

## 5. Rebuild and restart containers

```bash
cd /opt/substrack
sudo docker-compose up --build -d
```

---

## 6. Verify

- Open `https://yourdomain.com` — should load with a valid SSL certificate (padlock in browser)
- Register or log in with email/password
- Try **Continue with Google** — should open the Google OAuth flow and redirect back correctly

---

## Troubleshooting

**Google OAuth redirect mismatch error:**
The redirect URI in Google Cloud Console must exactly match `GOOGLE_REDIRECT_URI` in `.env` — including `https://`, no trailing slash.

**Mixed content warning (HTTPS page loading HTTP resources):**
Make sure `FRONTEND_URL` and `CORS_ORIGINS` are set to `https://` not `http://`.

**Cookie not being set after login:**
Make sure `COOKIE_SECURE=true` in `.env` — cookies with `Secure` flag only work over HTTPS.

**Cloudflare SSL error (526 Invalid SSL certificate):**
Make sure SSL mode is set to **Full (strict)** not **Flexible** in Cloudflare SSL/TLS settings.
