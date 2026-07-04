#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env.docker ]]; then
  echo "[docker-backup] error: missing .env.docker" >&2
  exit 1
fi
mkdir -p backups
source .env.docker
POSTGRES_DB="${POSTGRES_DB:-trade_proposer}"
POSTGRES_USER="${POSTGRES_USER:-trade_proposer}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="/backups/trade_proposer_${stamp}.dump"

docker compose --env-file .env.docker exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$output"

echo "[docker-backup] wrote backups/trade_proposer_${stamp}.dump"
