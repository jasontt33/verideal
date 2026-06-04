#!/usr/bin/env bash
# Tar this repo, push to S3, and (re)deploy on the EC2 via SSM.
#
# Usage:
#   ./deploy.sh
#
# Requires: aws CLI with credentials that can write to S3_BUCKET and
# call ssm:SendCommand on $INSTANCE_ID. No SSH key needed — uses SSM.

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
INSTANCE_ID="${INSTANCE_ID:-i-0ff83c5e0b2eeaab3}"
S3_BUCKET="${S3_BUCKET:-basic-ci-bucket}"
S3_KEY="${S3_KEY:-ap-dashboard/ap-dashboard.tar.gz}"
REMOTE_DIR="${REMOTE_DIR:-/data/ap-dashboard}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAR_PATH="${TMPDIR:-/tmp}/ap-dashboard.tar.gz"

# ── 1. Tar the repo ─────────────────────────────────────────────────
echo "→ Building tarball: $TAR_PATH"
tar -C "$REPO_ROOT" \
    --exclude='backend/.venv' \
    --exclude='backend/.pytest_cache' \
    --exclude='backend/.coverage' \
    --exclude='__pycache__' \
    --exclude='.DS_Store' \
    --exclude='.git' \
    --exclude='.claude' \
    --exclude='*.pyc' \
    --exclude='deploy.sh' \
    --exclude='.env' \
    -czf "$TAR_PATH" .

SIZE=$(du -h "$TAR_PATH" | awk '{print $1}')
echo "  packaged $SIZE"

# ── 2. Upload to S3 ─────────────────────────────────────────────────
echo "→ Uploading to s3://$S3_BUCKET/$S3_KEY"
aws s3 cp "$TAR_PATH" "s3://$S3_BUCKET/$S3_KEY" --region "$AWS_REGION" >/dev/null
echo "  uploaded"

# ── 3. Remote deploy via SSM ────────────────────────────────────────
# - Pull tar from S3
# - Untar over the existing tree (preserves .env and named volumes)
# - Generate .env on first run with a random POSTGRES_PASSWORD
# - docker compose up -d --build
REMOTE_SCRIPT=$(cat <<EOF
set -e
mkdir -p $REMOTE_DIR
cd $REMOTE_DIR
aws s3 cp s3://$S3_BUCKET/$S3_KEY .
tar -xzf ap-dashboard.tar.gz
if [ ! -f .env ]; then
  PG_PW=\$(openssl rand -hex 16)
  printf '%s\n' \\
    "POSTGRES_USER=ap_user" \\
    "POSTGRES_PASSWORD=\${PG_PW}" \\
    "POSTGRES_DB=ap_review" \\
    "POSTGRES_PORT=5432" \\
    "WEB_PORT=8501" \\
    > .env
  echo "Generated .env with random password"
fi
docker compose up -d --build
sleep 4
docker compose ps
echo === RECENT WEB LOGS ===
docker compose logs --tail=15 web
echo === HEALTH ===
PORT=\$(grep ^WEB_PORT .env | cut -d= -f2)
curl -sS -o /dev/null -w "HTTP:%{http_code}\n" "http://localhost:\${PORT}/api/health"
EOF
)

PARAMS_FILE="${TMPDIR:-/tmp}/ap-deploy-params.json"
jq -n --arg script "$REMOTE_SCRIPT" \
  '{commands: [$script]}' > "$PARAMS_FILE"

echo "→ Sending SSM command to $INSTANCE_ID"
CMD_ID=$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "AP dashboard deploy" \
  --timeout-seconds 600 \
  --parameters "file://$PARAMS_FILE" \
  --query "Command.CommandId" --output text)

echo "  command id: $CMD_ID"
echo "→ Waiting for completion (build can take 1–3 min)…"

while :; do
  STATUS=$(aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$CMD_ID" \
    --instance-id "$INSTANCE_ID" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$STATUS" in
    Success|Failed|Cancelled|TimedOut) break ;;
    *) printf '.' ; sleep 5 ;;
  esac
done
echo

aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Out:StandardOutputContent,Err:StandardErrorContent}' \
  --output text

if [ "$STATUS" != "Success" ]; then
  echo "✗ Deploy ended with status: $STATUS" >&2
  exit 1
fi

echo "✓ Deploy complete."
