#!/usr/bin/env bash
set -euo pipefail
exec docker compose --env-file .env.docker down "$@"
