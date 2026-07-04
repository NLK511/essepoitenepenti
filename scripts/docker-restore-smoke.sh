#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env.docker ]]; then
  echo "[docker-restore-smoke] error: missing .env.docker" >&2
  exit 1
fi
backup_path="${1:-}"
if [[ -z "$backup_path" ]]; then
  backup_path="$(ls -t backups/*.dump 2>/dev/null | head -1 || true)"
fi
if [[ -z "$backup_path" || ! -f "$backup_path" ]]; then
  echo "[docker-restore-smoke] error: provide a backup path or create one with scripts/docker-backup.sh" >&2
  exit 1
fi
source .env.docker
POSTGRES_USER="${POSTGRES_USER:-trade_proposer}"
smoke_db="trade_proposer_restore_smoke"
file_name="$(basename "$backup_path")"

cat "$backup_path" | docker compose --env-file .env.docker exec -T postgres sh -c "cat > /tmp/$file_name"
docker compose --env-file .env.docker exec -T postgres sh -c \
  "dropdb -U '$POSTGRES_USER' --if-exists '$smoke_db' && createdb -U '$POSTGRES_USER' '$smoke_db' && pg_restore -U '$POSTGRES_USER' -d '$smoke_db' '/tmp/$file_name'"

docker compose --env-file .env.docker run --rm \
  -e POSTGRES_TEST_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${smoke_db}" \
  migrate python scripts/check_postgres_validation.py

docker compose --env-file .env.docker exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$smoke_db"
echo "[docker-restore-smoke] restore smoke passed for $backup_path"
