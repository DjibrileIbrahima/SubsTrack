FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Run migrations then start server.
# --proxy-headers makes uvicorn derive the client IP from X-Forwarded-For so the
# rate limiter keys on the real client instead of the nginx container's IP.
# Trusting all proxy IPs ("*") is safe only because this port is never published —
# the only route to it is the nginx service on the compose network.
CMD alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
