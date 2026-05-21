# AWS Deployment Guide

## Prerequisites
- AWS account with an existing EC2 instance (t3.micro or larger)
- GitHub repository with the project

---

## 1. EC2 Security Group
Open the required ports:
- EC2 → Instances → your instance → **Security** tab → click the security group
- **Edit inbound rules** → make sure you have both:

| Type | Port | Source |
|---|---|---|
| SSH | 22 | 0.0.0.0/0 |
| HTTP | 80 | 0.0.0.0/0 |

---

## 2. Elastic IP (permanent IP address)
Without an Elastic IP, your instance gets a new IP every time it restarts.

- EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**
- Select the new IP → **Actions → Associate Elastic IP address**
- Select your instance → **Associate**

Note the IP — you'll use it everywhere.

---

## 3. Connect to the instance
- EC2 → Instances → select your instance → **Connect**
- Select **EC2 Instance Connect** tab
- Username: `ec2-user` (Amazon Linux) or `ubuntu` (Ubuntu)
- Click **Connect**

---

## 4. Install Docker

```bash
sudo yum update -y
sudo yum install -y docker git
sudo service docker start
sudo usermod -aG docker $USER
sudo chkconfig docker on
sudo systemctl enable docker
```

Log out and reconnect for the Docker group to take effect.

---

## 5. Install Docker Compose

```bash
sudo curl -L https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose version
```

---

## 6. Clone the repo

```bash
sudo git clone https://github.com/DjibrileIbrahima/SubsTrack.git /opt/substrack
sudo chown -R $USER:$USER /opt/substrack
cd /opt/substrack
```

---

## 7. Configure environment variables

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Generate the required secrets directly on the server:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Fill in the `.env` with production values:

```env
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_secret
PLAID_ENV=sandbox

POSTGRES_PASSWORD=strong_random_password
DATABASE_URL=postgresql+asyncpg://substrack:strong_random_password@db:5432/substrack

ENCRYPTION_KEY=generated_above
JWT_SECRET=generated_above

GOOGLE_CLIENT_ID=placeholder
GOOGLE_CLIENT_SECRET=placeholder
GOOGLE_REDIRECT_URI=http://YOUR_ELASTIC_IP/api/auth/google/callback

FRONTEND_URL=http://YOUR_ELASTIC_IP
CORS_ORIGINS=http://YOUR_ELASTIC_IP

COOKIE_SECURE=false
REDIS_URL=redis://redis:6379
```

> **Note:** `COOKIE_SECURE=false` and `GOOGLE_CLIENT_ID=placeholder` are fine for testing without a domain. Once you have a domain and HTTPS, update these.

Make `POSTGRES_PASSWORD` available to Docker Compose at the system level:

```bash
sudo sh -c 'echo "POSTGRES_PASSWORD=$(grep POSTGRES_PASSWORD backend/.env | cut -d= -f2)" >> /etc/environment'
```

Log out and reconnect, then verify:
```bash
echo $POSTGRES_PASSWORD
```

---

## 8. Build and start containers

```bash
cd /opt/substrack
sudo docker-compose build
sudo docker-compose up -d
```

Verify all containers are running:
```bash
sudo docker-compose ps
```

You should see 5 containers: `db`, `redis`, `backend`, `worker`, `frontend`.

---

## 9. Run database migrations

```bash
sudo docker-compose exec backend python -m alembic upgrade head
```

---

## 10. Verify

Open `http://YOUR_ELASTIC_IP` in your browser. You should see the app.

To test Plaid, use sandbox credentials:
- **Username:** `user_good`
- **Password:** `pass_good`

---

## 11. Set up auto-deploy with GitHub Actions

Generate an SSH key pair on the server for GitHub Actions to use:

```bash
ssh-keygen -t ed25519 -C "github-deploy" -f ~/.ssh/deploy_key -N ""
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/deploy_key
```

Copy the private key output (including the `-----BEGIN` and `-----END` lines).

Add these secrets to GitHub at `github.com/YOUR_USERNAME/SubsTrack/settings/secrets/actions`:

| Secret | Value |
|---|---|
| `SERVER_IP` | Your Elastic IP |
| `SERVER_USER` | `ec2-user` |
| `SSH_PRIVATE_KEY` | The private key output from above |

From now on, every push to `master` that passes tests will automatically deploy to your server.

---

## After a server reboot

Containers have `restart: unless-stopped` and Docker is enabled on boot, so they come back automatically. If for any reason they don't:

```bash
cd /opt/substrack
export POSTGRES_PASSWORD=$(grep POSTGRES_PASSWORD backend/.env | cut -d '=' -f2)
sudo docker-compose up -d
```

---

## Useful commands

**View logs:**
```bash
sudo docker-compose logs -f backend
sudo docker-compose logs -f worker
sudo docker-compose logs -f frontend
```

**Restart a single service:**
```bash
sudo docker-compose restart backend
```

**Deploy manually:**
```bash
cd /opt/substrack
git pull
sudo docker-compose up --build -d
sudo docker-compose exec -T backend python -m alembic upgrade head
```

---

## Adding a domain later

Once you have a domain:

1. Add it to Cloudflare → set DNS A record to your Elastic IP with proxy enabled (orange cloud)
2. Set SSL mode to **Full (strict)** in Cloudflare
3. Update `backend/.env`:
   ```
   FRONTEND_URL=https://yourdomain.com
   CORS_ORIGINS=https://yourdomain.com
   COOKIE_SECURE=true
   GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback
   ```
4. Set up Google OAuth with the real domain as the redirect URI
5. Rebuild and restart:
   ```bash
   sudo docker-compose up --build -d
   ```
