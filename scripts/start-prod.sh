#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"
STATE_DIR="${ROOT_DIR}/.prod-run"
API_PID_FILE="${STATE_DIR}/api.pid"
API_LOG_FILE="${STATE_DIR}/api.log"
WORKER_PID_FILE="${STATE_DIR}/worker.pid"
SCHEDULER_PID_FILE="${STATE_DIR}/scheduler.pid"
SCHEDULER_LOG_FILE="${STATE_DIR}/scheduler.log"
META_FILE="${STATE_DIR}/meta.env"
AUDIT_LOG_FILE="${STATE_DIR}/lifecycle-audit.log"

SKIP_FRONTEND_BUILD="false"
ALLOW_DEGRADED_PREFLIGHT="false"
START_HOST=""
START_PORT=""

log() {
  printf '[start-prod] %s\n' "$1"
}

log_audit() {
  mkdir -p "$STATE_DIR"
  local timestamp
  timestamp="$(date -Is)"
  printf '[%s] [start-prod pid=%s ppid=%s] %s\n' "$timestamp" "$$" "${PPID:-unknown}" "$1" >> "$AUDIT_LOG_FILE"
}

process_snapshot() {
  local label="$1"
  shift || true
  log_audit "process snapshot: ${label}"
  for pid in "$@"; do
    [[ -z "${pid:-}" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      ps -o pid,ppid,pgid,sid,stat,rss,etime,cmd -p "$pid" >> "$AUDIT_LOG_FILE" 2>&1 || true
    else
      log_audit "pid ${pid} is not running"
    fi
  done
}

fail() {
  printf '[start-prod] error: %s\n' "$1" >&2
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
    fail "could not connect to PostgreSQL. Ensure the configured database is reachable before starting production-style services."
  fi
}

usage() {
  cat <<EOF
Usage: scripts/start-prod.sh [options]

Options:
  --host <host>               Host for uvicorn (default: APP_HOST or 0.0.0.0)
  --port <port>               Port for uvicorn (default: APP_PORT or 8000)
  --skip-frontend-build       Assume frontend assets are already built
  --allow-degraded-preflight  Start even if preflight fails
  --help                      Show this help message
EOF
}

trim() {
  local value="$*"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_env_file() {
  local path="$1"
  log "loading environment from ${path}"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(trim "$line")"
    [[ -z "$line" ]] && continue
    [[ "$line" != *=* ]] && continue
    local key="${line%%=*}"
    local value="${line#*=}"
    key="$(trim "$key")"
    value="$(trim "$value")"
    export "$key"="$value"
  done < "$path"
}

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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-frontend-build)
      SKIP_FRONTEND_BUILD="true"
      shift
      ;;
    --allow-degraded-preflight)
      ALLOW_DEGRADED_PREFLIGHT="true"
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
    --help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  load_env_file "$ENV_FILE"
else
  log "warning: ${ENV_FILE} not found; using defaults"
fi

export APP_ENV="${APP_ENV:-production}"
START_HOST="${START_HOST:-${APP_HOST:-0.0.0.0}}"
START_PORT="${START_PORT:-${APP_PORT:-8000}}"

[[ -d "$VENV_DIR" ]] || fail "missing ${VENV_DIR}; run ./scripts/setup.sh first"
VENV_PYTHON="${VENV_DIR}/bin/python"
[[ -x "$VENV_PYTHON" ]] || fail "missing ${VENV_PYTHON}; run ./scripts/setup.sh first"
DATABASE_URL_VALUE="${DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:5432/trade_proposer}"

mkdir -p "$STATE_DIR"
log_audit "startup requested args=$* cwd=$(pwd) user=$(id -un 2>/dev/null || true) host=${START_HOST} port=${START_PORT} skip_frontend_build=${SKIP_FRONTEND_BUILD}"
ps -o pid,ppid,pgid,sid,stat,rss,etime,cmd -p "$$" >> "$AUDIT_LOG_FILE" 2>&1 || true
existing_api_pid="$(read_pid_file "$API_PID_FILE")"
existing_worker_pid="$(read_pid_file "$WORKER_PID_FILE")"
existing_scheduler_pid="$(read_pid_file "$SCHEDULER_PID_FILE")"
if is_running_pid "$existing_api_pid" || is_running_pid "$existing_worker_pid" || is_running_pid "$existing_scheduler_pid"; then
  fail "services already appear to be running; use ./scripts/stop-prod.sh first"
fi

if [[ -d "$FRONTEND_DIR" && "$SKIP_FRONTEND_BUILD" != "true" ]]; then
  command -v npm >/dev/null 2>&1 || fail "npm is required to build the frontend"
  log "installing frontend dependencies"
  (
    cd "$FRONTEND_DIR"
    npm ci
  )
  log "building frontend assets"
  (
    cd "$FRONTEND_DIR"
    NODE_ENV=production npm run build
  )
elif [[ "$SKIP_FRONTEND_BUILD" != "true" ]]; then
  fail "missing ${FRONTEND_DIR}; can't build frontend"
else
  log "skipping frontend build (assumed already built)"
fi

if [[ "$SKIP_FRONTEND_BUILD" != "true" ]]; then
  log "frontend assets available in ${FRONTEND_DIR}/dist"
fi

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

rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$SCHEDULER_PID_FILE" "$META_FILE"

API_PID=""
WORKER_PID=""
SCHEDULER_PID=""
SHUTDOWN_REASON="normal_exit"

mark_signal_shutdown() {
  SHUTDOWN_REASON="signal_${1}"
  log_audit "supervisor received ${1}; command=${0} ${*}; cwd=$(pwd); user=$(id -un 2>/dev/null || true)"
  process_snapshot "before signal cleanup ${1}" "$API_PID" "$WORKER_PID" "$SCHEDULER_PID"
  exit 128
}

cleanup() {
  local exit_code=$?
  set +e
  if [[ "$SHUTDOWN_REASON" == "normal_exit" && "$exit_code" -ne 0 ]]; then
    SHUTDOWN_REASON="error_exit_${exit_code}"
  fi
  log_audit "cleanup started reason=${SHUTDOWN_REASON} exit_code=${exit_code}"
  process_snapshot "cleanup start" "$API_PID" "$WORKER_PID" "$SCHEDULER_PID"
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    log "stopping worker (pid ${WORKER_PID})"
    log_audit "sending SIGTERM to worker pid=${WORKER_PID} reason=${SHUTDOWN_REASON}"
    kill "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  if [[ -n "$SCHEDULER_PID" ]] && kill -0 "$SCHEDULER_PID" 2>/dev/null; then
    log "stopping scheduler (pid ${SCHEDULER_PID})"
    log_audit "sending SIGTERM to scheduler pid=${SCHEDULER_PID} reason=${SHUTDOWN_REASON}"
    kill "$SCHEDULER_PID" 2>/dev/null || true
    wait "$SCHEDULER_PID" 2>/dev/null || true
  fi
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    log "stopping api (pid ${API_PID})"
    log_audit "sending SIGTERM to api pid=${API_PID} reason=${SHUTDOWN_REASON}"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  log_audit "cleanup finished reason=${SHUTDOWN_REASON} exit_code=${exit_code}"
  rm -f "$API_PID_FILE" "$WORKER_PID_FILE" "$SCHEDULER_PID_FILE" "$META_FILE"
  rmdir "$STATE_DIR" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT
trap 'mark_signal_shutdown INT' INT
trap 'mark_signal_shutdown TERM' TERM

log "starting api on ${START_HOST}:${START_PORT}"
(
  cd "$ROOT_DIR"
  exec "$VENV_PYTHON" -m uvicorn trade_proposer_app.app:app --host "$START_HOST" --port "$START_PORT" >> "$API_LOG_FILE" 2>&1
) &
API_PID=$!
echo "$API_PID" > "$API_PID_FILE"
log_audit "started api pid=${API_PID}"

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
echo "$WORKER_PID" > "$WORKER_PID_FILE"
log_audit "started worker pid=${WORKER_PID} worker_id=${WORKER_ID} log=${WORKER_LOG_FILE}"

log "starting scheduler"
(
  cd "$ROOT_DIR"
  exec "$VENV_PYTHON" -m trade_proposer_app.scheduler >> "$SCHEDULER_LOG_FILE" 2>&1
) &
SCHEDULER_PID=$!
echo "$SCHEDULER_PID" > "$SCHEDULER_PID_FILE"
log_audit "started scheduler pid=${SCHEDULER_PID}"

cat > "$META_FILE" <<EOF
HOST=${START_HOST}
PORT=${START_PORT}
SKIP_FRONTEND_BUILD=${SKIP_FRONTEND_BUILD}
ALLOW_DEGRADED_PREFLIGHT=${ALLOW_DEGRADED_PREFLIGHT}
API_PID=${API_PID}
WORKER_PID=${WORKER_PID}
WORKER_ID=${WORKER_ID}
WORKER_LOG_FILE=${WORKER_LOG_FILE}
SCHEDULER_PID=${SCHEDULER_PID}
EOF

log "services started"
printf '\n'
printf 'API:       http://%s:%s/api/health\n' "$START_HOST" "$START_PORT"
printf 'Frontend:  served from the API at http://%s:%s/ (assets under frontend/dist)\n' "$START_HOST" "$START_PORT"
printf 'Preflight: http://%s:%s/api/health/preflight\n' "$START_HOST" "$START_PORT"
printf 'Worker:    running in background (pid %s)\n' "$WORKER_PID"
printf 'Scheduler: running in background (pid %s)\n' "$SCHEDULER_PID"
printf 'State dir: %s\n' "$STATE_DIR"
printf '\n'
printf 'Use ./scripts/stop-prod.sh to stop these processes from another terminal.\n'
printf 'Press Ctrl+C to stop all started processes here as well.\n'

while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    SHUTDOWN_REASON="api_exited"
    log_audit "api process exited unexpectedly pid=${API_PID}; check ${API_LOG_FILE}"
    process_snapshot "api exited" "$WORKER_PID" "$SCHEDULER_PID"
    log "error: api process (pid ${API_PID}) exited. check ${API_LOG_FILE} for details."
    exit 1
  fi
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    SHUTDOWN_REASON="worker_exited"
    log_audit "worker process exited unexpectedly pid=${WORKER_PID}; check ${WORKER_LOG_FILE}"
    process_snapshot "worker exited" "$API_PID" "$SCHEDULER_PID"
    log "error: worker process (pid ${WORKER_PID}) exited. check ${WORKER_LOG_FILE} for details."
    exit 1
  fi
  if ! kill -0 "$SCHEDULER_PID" 2>/dev/null; then
    SHUTDOWN_REASON="scheduler_exited"
    log_audit "scheduler process exited unexpectedly pid=${SCHEDULER_PID}; check ${SCHEDULER_LOG_FILE}"
    process_snapshot "scheduler exited" "$API_PID" "$WORKER_PID"
    log "error: scheduler process (pid ${SCHEDULER_PID}) exited. check ${SCHEDULER_LOG_FILE} for details."
    exit 1
  fi
  sleep 1
done
