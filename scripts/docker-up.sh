#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.docker ]]; then
  echo "[docker-up] error: missing $ROOT_DIR/.env.docker. Copy .env.docker.example and set safe secrets." >&2
  exit 1
fi

compose=(docker compose --env-file .env.docker)

# Bring the database up first and wait for its healthcheck. Docker's daemon-level
# restart policy does not honor Compose depends_on ordering after a host reboot,
# so this script makes startup ordering explicit and repeatable.
"${compose[@]}" up -d --wait postgres

# Run migrations as an explicit one-shot step before starting long-lived app
# services. Keeping runtime services independent from the one-shot migrate
# container avoids boot-time failures when Docker restarts containers directly.
"${compose[@]}" run --rm migrate

exec "${compose[@]}" up -d --wait "$@" api worker scheduler
