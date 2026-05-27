#!/usr/bin/env bash
# Pulls all /substrack/* parameters from AWS SSM Parameter Store
# and writes them to backend/.env.
# Requires the EC2 instance to have an IAM role with ssm:GetParametersByPath.
set -euo pipefail

DEST="$(dirname "$0")/backend/.env"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Fetching secrets from Parameter Store (region: $REGION)..."

aws ssm get-parameters-by-path \
    --path "/substrack/" \
    --with-decryption \
    --recursive \
    --region "$REGION" \
    --query "Parameters[*].[Name,Value]" \
    --output text \
| while IFS=$'\t' read -r name value; do
    key="${name#/substrack/}"
    printf '%s=%s\n' "$key" "$value"
done > "$DEST"

echo "Wrote $(wc -l < "$DEST") variables to $DEST"
