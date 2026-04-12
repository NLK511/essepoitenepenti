#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"
RUN_SCHEDULER_ONCE="false"
ALLOW_DEGRADED_PREFLIGHT="false"
START_FRONTEND="true"
START_PORT="${APP_PORT:-8000}"
START_HOST="${APP_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
STATE_DIR="${ROOT_DIR}/.dev-run"
API_PID_FILE="${STATE_DIR}/api.pid"
WORKER_PID_FILE="${STATE_DIR}/worker.pid"
SCHEDULER_PID_FILE="${STATE_DIR}/scheduler.pid"
FRONTEND_PID_FILE="${STATE_DIR}/frontend.pid"
META_FILE="${STATE_DIR}/meta.env"
API_PID=""
WORKER_PID=""
SCHEDULER_PID=""
FRONTEND_PID=""

log() {
  printf '[start-dev] %s\n' "$1"
}

fail() {
  printf '[start-dev] error: %s\n' "$1" >&2
  exit 1
}

ensure_database_connection() {
  local database_url="$1"
  if [[ "$database_url" == sqlite:* ]]; then
    log "using SQLite database: ${database_url}"
    return 0
  fi
  if [[ "$database_url" != postgresql* && "$database_url" != postgres:* ]]; then
    fail "unsupported DATABASE_URL backend: ${database_url}"
  fi
  log "checking PostgreSQL connectivity"
  if ! DATABASE_URL_TO_CHECK="$database_url" "$VENV_PYTHON" - <<'PY'
import os
import sys
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL_TO_CHECK"]
engine = create_engine(url, future=True)
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as exc:  # pragma: no cover - script path
    print(exc, file=sys.stderr)
    sys.exit(1)
finally:
    engine.dispose()
PY
  then
    fail "could not connect to PostgreSQL. Start local services with 'docker compose up -d postgres' or switch DATABASE_URL to a SQLite URL for no-service local mode."
  fi
}

usage() {
  cat <<EOF
Usage: scripts/start-dev.sh [options]

Options:
  --run-scheduler-once        Run the scheduler enqueue pass before starting services
  --allow-degraded-preflight  Allow startup even if the internal pipeline preflight reports failure
  --backend-only              Start only the API and worker, not the Vite frontend dev server
  --host <host>               Host for uvicorn (default: APP_HOST or 0.0.0.0)
  --port <port>               Port for uvicorn (default: APP_PORT or 8000)
  --frontend-port <port>      Port for Vite dev server (default: FRONTEND_PORT or 5173)
  --help                      Show this help

What this script does:
  1. Verifies .venv and .env exist
  2. Applies pending database migrations
  3. Runs internal pipeline preflight checks
  4. Starts the FastAPI API server
  5. Starts the worker
  6. Starts the scheduler poller
  7. Starts the React/Vite frontend dev server unless --backend-only is set
  8. Writes PID files under .dev-run/
  9. Waits until one process exits or you press Ctrl+C
  10. Shuts all started processes down cleanly
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-scheduler-once)
      RUN_SCHEDULER_ONCE="true"
      shift
      ;;
    --allow-degraded-preflight|--allow-degraded-prototype)
      ALLOW_DEGRADED_PREFLIGHT="true"
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

read_env_value() {
  "$VENV_PYTHON" - "$1" "$2" <<'PY'
import sys
from pathlib import Path

if len(sys.argv) < 3:
    sys.exit(0)
key = sys.argv[1]
path = Path(sys.argv[2])
if not path.exists():
    sys.exit(0)
value = ""
for line in path.read_text().splitlines():
    if line.startswith(f"{key}="):
        value = line.split("=", 1)[1]
        break
sys.stdout.write(value)
PY
}

VENV_PYTHON="${VENV_DIR}/bin/python"
[[ -x "$VENV_PYTHON" ]] || fail "missing ${VENV_PYTHON}; run ./scripts/setup.sh first"
DATABASE_URL_VALUE="$(read_env_value DATABASE_URL "$ENV_FILE")"
FILE_AUTH_TOKEN="$(read_env_value SINGLE_USER_AUTH_TOKEN "$ENV_FILE")"

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
existing_scheduler_pid="$(read_pid_file "$SCHEDULER_PID_FILE")"
existing_frontend_pid="$(read_pid_file "$FRONTEND_PID_FILE")"
if is_running_pid "$existing_api_pid" || is_running_pid "$existing_worker_pid" || is_running_pid "$existing_scheduler_pid" || is_running_pid "$existing_frontend_pid"; then
  fail "services already appear to be running; use ./scripts/stop-dev.sh first"
fi

rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$SCHEDULER_PID_FILE" "$FRONTEND_PID_FILE" "$META_FILE"

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
  if [[ -n "$SCHEDULER_PID" ]] && kill -0 "$SCHEDULER_PID" 2>/dev/null; then
    log "stopping scheduler (pid ${SCHEDULER_PID})"
    kill "$SCHEDULER_PID" 2>/dev/null || true
    wait "$SCHEDULER_PID" 2>/dev/null || true
  fi
  rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$SCHEDULER_PID_FILE" "$FRONTEND_PID_FILE" "$META_FILE"
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

ensure_database_connection "$DATABASE_URL_VALUE"

log "applying database migrations"
(
  cd "$ROOT_DIR"
  "$VENV_PYTHON" -m trade_proposer_app.migrations
)

log "running internal pipeline preflight"
PRECHECK_OUTPUT="$(
  cd "$ROOT_DIR"
  "$VENV_PYTHON" - <<'PY'
from trade_proposer_app.services.preflight import AppPreflightService
report = AppPreflightService().run()
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
if [[ "$PRECHECK_STATUS" == "failed" && "$ALLOW_DEGRADED_PREFLIGHT" != "true" ]]; then
  fail "internal pipeline preflight failed; fix the reported issues or rerun with --allow-degraded-preflight"
fi
if [[ "$PRECHECK_STATUS" == "failed" && "$ALLOW_DEGRADED_PREFLIGHT" == "true" ]]; then
  log "continuing despite failed internal pipeline preflight because --allow-degraded-preflight was set"
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

WORKER_ID="$($VENV_PYTHON - <<'PY'
import uuid
import socket
import os
print(f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}")
PY
)"
WORKER_LOG_DIR="$STATE_DIR/workers"
WORKER_LOG_FILE="$WORKER_LOG_DIR/${WORKER_ID}.log"
mkdir -p "$WORKER_LOG_DIR"
log "starting worker (${WORKER_ID})"
(
  cd "$ROOT_DIR"
  WORKER_ID="$WORKER_ID" WORKER_LOG_FILE="$WORKER_LOG_FILE" exec "$VENV_PYTHON" -m trade_proposer_app.workers.tasks >> "$WORKER_LOG_FILE" 2>&1
) &
WORKER_PID=$!
printf '%s\n' "$WORKER_PID" > "$WORKER_PID_FILE"

log "starting scheduler"
(
  cd "$ROOT_DIR"
  exec "$VENV_PYTHON" -m trade_proposer_app.scheduler
) &
SCHEDULER_PID=$!
printf '%s\n' "$SCHEDULER_PID" > "$SCHEDULER_PID_FILE"

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
ALLOW_DEGRADED_PREFLIGHT=${ALLOW_DEGRADED_PREFLIGHT}
ALLOW_DEGRADED_PROTOTYPE=${ALLOW_DEGRADED_PREFLIGHT}
START_FRONTEND=${START_FRONTEND}
API_PID=${API_PID}
WORKER_PID=${WORKER_PID}
WORKER_ID=${WORKER_ID}
WORKER_LOG_FILE=${WORKER_LOG_FILE}
SCHEDULER_PID=${SCHEDULER_PID}
FRONTEND_PID=${FRONTEND_PID}
EOF

printf '\n'
printf 'Services started:\n'
printf '  api:      pid %s\n' "$API_PID"
printf '  worker:   pid %s\n' "$WORKER_PID"
printf '  scheduler: pid %s\n' "$SCHEDULER_PID"
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
  if ! kill -0 "$SCHEDULER_PID" 2>/dev/null; then
    fail "scheduler process exited"
  fi
  if [[ "$START_FRONTEND" == "true" ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend process exited"
  fi
  sleep 1
done
