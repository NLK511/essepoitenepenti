#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/.dev-run"
API_PID_FILE="${STATE_DIR}/api.pid"
WORKER_PID_FILE="${STATE_DIR}/worker.pid"
FRONTEND_PID_FILE="${STATE_DIR}/frontend.pid"
META_FILE="${STATE_DIR}/meta.env"

log() {
  printf '[stop-dev] %s\n' "$1"
}

usage() {
  cat <<EOF
Usage: scripts/stop-dev.sh

Stops the API, worker, and optional frontend dev server started by scripts/start-dev.sh using PID files under .dev-run/.
EOF
}

if [[ ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

read_pid_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    tr -d '[:space:]' < "$path"
  fi
}

stop_pid() {
  local name="$1"
  local pid="$2"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    log "${name} pid ${pid} is not running"
    return 0
  fi

  log "stopping ${name} (pid ${pid})"
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 50); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done

  log "${name} did not exit after SIGTERM; sending SIGKILL"
  kill -9 "$pid" 2>/dev/null || true
}

API_PID="$(read_pid_file "$API_PID_FILE")"
WORKER_PID="$(read_pid_file "$WORKER_PID_FILE")"
FRONTEND_PID="$(read_pid_file "$FRONTEND_PID_FILE")"

if [[ -z "$API_PID" && -z "$WORKER_PID" && -z "$FRONTEND_PID" ]]; then
  log "no PID files found in ${STATE_DIR}; nothing to stop"
  exit 0
fi

stop_pid "frontend" "$FRONTEND_PID"
stop_pid "api" "$API_PID"
stop_pid "worker" "$WORKER_PID"

rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$FRONTEND_PID_FILE" "$META_FILE"
rmdir "$STATE_DIR" 2>/dev/null || true

log "done"
