#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env.docker ]]; then
  echo "[docker-up] error: missing .env.docker. Copy .env.docker.example and set safe secrets." >&2
  exit 1
fi

exec docker compose --env-file .env.docker up -d "$@"
