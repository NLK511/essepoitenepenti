#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"
RUN_SCHEDULER_ONCE="false"
ALLOW_DEGRADED_PROTOTYPE="false"
START_FRONTEND="true"
START_PORT="${APP_PORT:-8000}"
START_HOST="${APP_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
STATE_DIR="${ROOT_DIR}/.dev-run"
API_PID_FILE="${STATE_DIR}/api.pid"
WORKER_PID_FILE="${STATE_DIR}/worker.pid"
FRONTEND_PID_FILE="${STATE_DIR}/frontend.pid"
META_FILE="${STATE_DIR}/meta.env"
API_PID=""
WORKER_PID=""
FRONTEND_PID=""

log() {
  printf '[start-dev] %s\n' "$1"
}

fail() {
  printf '[start-dev] error: %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: scripts/start-dev.sh [options]

Options:
  --run-scheduler-once        Run the scheduler enqueue pass before starting services
  --allow-degraded-prototype  Allow startup even if prototype preflight status is failed
  --backend-only              Start only the API and worker, not the Vite frontend dev server
  --host <host>               Host for uvicorn (default: APP_HOST or 0.0.0.0)
  --port <port>               Port for uvicorn (default: APP_PORT or 8000)
  --frontend-port <port>      Port for Vite dev server (default: FRONTEND_PORT or 5173)
  --help                      Show this help

What this script does:
  1. Verifies .venv and .env exist
  2. Applies pending database migrations
  3. Runs prototype preflight checks
  4. Starts the FastAPI API server
  5. Starts the worker
  6. Starts the React/Vite frontend dev server unless --backend-only is set
  7. Writes PID files under .dev-run/
  8. Waits until one process exits or you press Ctrl+C
  9. Shuts all started processes down cleanly
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-scheduler-once)
      RUN_SCHEDULER_ONCE="true"
      shift
      ;;
    --allow-degraded-prototype)
      ALLOW_DEGRADED_PROTOTYPE="true"
      shift
      ;;
    --backend-only)
      START_FRONTEND="false"
      shift
      ;;
    --host)
      shift
      [[ $# -gt 0 ]] || fail "missing value for --host"
      START_HOST="$1"
      shift
      ;;
    --port)
      shift
      [[ $# -gt 0 ]] || fail "missing value for --port"
      START_PORT="$1"
      shift
      ;;
    --frontend-port)
      shift
      [[ $# -gt 0 ]] || fail "missing value for --frontend-port"
      FRONTEND_PORT="$1"
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[[ -d "$VENV_DIR" ]] || fail "missing ${VENV_DIR}; run ./scripts/setup.sh first"
[[ -f "$ENV_FILE" ]] || fail "missing ${ENV_FILE}; run ./scripts/setup.sh first"

VENV_PYTHON="${VENV_DIR}/bin/python"
[[ -x "$VENV_PYTHON" ]] || fail "missing ${VENV_PYTHON}; run ./scripts/setup.sh first"

if [[ "$START_FRONTEND" == "true" ]]; then
  command -v npm >/dev/null 2>&1 || fail "npm is required to start the frontend dev server"
  [[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "missing frontend/node_modules; run ./scripts/setup.sh first"
fi

mkdir -p "$STATE_DIR"

read_pid_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    tr -d '[:space:]' < "$path"
  fi
}

is_running_pid() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

existing_api_pid="$(read_pid_file "$API_PID_FILE")"
existing_worker_pid="$(read_pid_file "$WORKER_PID_FILE")"
existing_frontend_pid="$(read_pid_file "$FRONTEND_PID_FILE")"
if is_running_pid "$existing_api_pid" || is_running_pid "$existing_worker_pid" || is_running_pid "$existing_frontend_pid"; then
  fail "services already appear to be running; use ./scripts/stop-dev.sh first"
fi

rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$FRONTEND_PID_FILE" "$META_FILE"

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    log "stopping frontend (pid ${FRONTEND_PID})"
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    log "stopping api (pid ${API_PID})"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    log "stopping worker (pid ${WORKER_PID})"
    kill "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$FRONTEND_PID_FILE" "$META_FILE"
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

log "applying database migrations"
(
  cd "$ROOT_DIR"
  "$VENV_PYTHON" -m trade_proposer_app.migrations
)

log "running prototype preflight"
PRECHECK_OUTPUT="$(
  cd "$ROOT_DIR"
  "$VENV_PYTHON" - <<'PY'
from trade_proposer_app.services.preflight import PrototypePreflightService
report = PrototypePreflightService().run()
print(report.status)
for check in report.checks:
    print(f"{check.status}|{check.name}|{check.message}")
PY
)"
PRECHECK_STATUS="$(printf '%s\n' "$PRECHECK_OUTPUT" | head -n 1)"
printf '%s\n' "$PRECHECK_OUTPUT" | tail -n +2 | while IFS='|' read -r check_status check_name check_message; do
  [[ -n "$check_name" ]] || continue
  log "preflight ${check_status}: ${check_name}: ${check_message}"
done
if [[ "$PRECHECK_STATUS" == "failed" && "$ALLOW_DEGRADED_PROTOTYPE" != "true" ]]; then
  fail "prototype preflight failed; fix the reported issues or rerun with --allow-degraded-prototype"
fi
if [[ "$PRECHECK_STATUS" == "failed" && "$ALLOW_DEGRADED_PROTOTYPE" == "true" ]]; then
  log "continuing despite failed prototype preflight because --allow-degraded-prototype was set"
fi

if [[ "$RUN_SCHEDULER_ONCE" == "true" ]]; then
  log "running scheduler enqueue pass once"
  (
    cd "$ROOT_DIR"
    "$VENV_PYTHON" -m trade_proposer_app.services.runs
  )
fi

log "starting api on ${START_HOST}:${START_PORT}"
(
  cd "$ROOT_DIR"
  exec "$VENV_PYTHON" -m uvicorn trade_proposer_app.app:app --host "$START_HOST" --port "$START_PORT"
) &
API_PID=$!
printf '%s\n' "$API_PID" > "$API_PID_FILE"

log "starting worker"
(
  cd "$ROOT_DIR"
  exec "$VENV_PYTHON" -m trade_proposer_app.workers.tasks
) &
WORKER_PID=$!
printf '%s\n' "$WORKER_PID" > "$WORKER_PID_FILE"

if [[ "$START_FRONTEND" == "true" ]]; then
  log "starting frontend dev server on ${FRONTEND_PORT}"
  (
    cd "$FRONTEND_DIR"
    exec npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
  ) &
  FRONTEND_PID=$!
  printf '%s\n' "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
fi

cat > "$META_FILE" <<EOF
HOST=${START_HOST}
PORT=${START_PORT}
FRONTEND_PORT=${FRONTEND_PORT}
RUN_SCHEDULER_ONCE=${RUN_SCHEDULER_ONCE}
ALLOW_DEGRADED_PROTOTYPE=${ALLOW_DEGRADED_PROTOTYPE}
START_FRONTEND=${START_FRONTEND}
API_PID=${API_PID}
WORKER_PID=${WORKER_PID}
FRONTEND_PID=${FRONTEND_PID}
EOF

printf '\n'
printf 'Services started:\n'
printf '  api:      pid %s\n' "$API_PID"
printf '  worker:   pid %s\n' "$WORKER_PID"
if [[ "$START_FRONTEND" == "true" ]]; then
  printf '  frontend: pid %s\n' "$FRONTEND_PID"
fi
printf '  state:    %s\n' "$STATE_DIR"
printf '\n'
printf 'Open in browser:\n'
if [[ "$START_FRONTEND" == "true" ]]; then
  printf '  frontend: http://localhost:%s/\n' "$FRONTEND_PORT"
fi
printf '  api:      http://localhost:%s/api/health\n' "$START_PORT"
printf '\n'
printf 'Use ./scripts/stop-dev.sh to stop all started processes from another terminal.\n'
printf 'Press Ctrl+C here to stop them as well.\n'
printf '\n'

while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    fail "api process exited"
  fi
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    fail "worker process exited"
  fi
  if [[ "$START_FRONTEND" == "true" ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend process exited"
  fi
  sleep 1
done
