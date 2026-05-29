#!/usr/bin/env bash
# Writes only the database credentials needed by docker-compose (db service).
# Application secrets are now injected natively by ECS from Parameter Store.
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Fetching db credentials from Parameter Store..."

POSTGRES_PASSWORD=$(aws ssm get-parameter \
  --name "/substrack/POSTGRES_PASSWORD" \
  --with-decryption \
  --region "$REGION" \
  --query "Parameter.Value" \
  --output text)

cat > "$(dirname "$0")/.env" <<EOF
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_USER=substrack
POSTGRES_DB=substrack
EOF

echo "Wrote .env for docker-compose."
