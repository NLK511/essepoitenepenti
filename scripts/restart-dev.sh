#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<EOF
Usage: scripts/restart-dev.sh [start-dev options]

Stops any running local dev services, then starts them again.
All arguments are forwarded to scripts/start-dev.sh.

Examples:
  ./scripts/restart-dev.sh
  ./scripts/restart-dev.sh --port 8010
  ./scripts/restart-dev.sh --run-scheduler-once
EOF
}

if [[ ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

"${ROOT_DIR}/scripts/stop-dev.sh"
exec "${ROOT_DIR}/scripts/start-dev.sh" "$@"
