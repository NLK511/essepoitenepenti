#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"
ENV_EXAMPLE_FILE="${ROOT_DIR}/.env.example"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_PORT="${APP_PORT:-8000}"
APP_HOST="${APP_HOST:-0.0.0.0}"
DATABASE_URL_DEFAULT="sqlite:///./trade_proposer.db"
REDIS_URL_DEFAULT="redis://localhost:6379/0"
PROTOTYPE_REPO_PATH_DEFAULT="${PROTOTYPE_REPO_PATH:-}"
PROTOTYPE_PYTHON_EXECUTABLE_DEFAULT="${PROTOTYPE_PYTHON_EXECUTABLE:-}"
FORCE_ENV_WRITE="false"
SKIP_PROTOTYPE_DEPS="false"
SKIP_FRONTEND_DEPS="false"

log() {
  printf '[setup] %s\n' "$1"
}

fail() {
  printf '[setup] error: %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: scripts/setup.sh [options]

Options:
  --force-env            Overwrite .env with generated local defaults
  --python <binary>      Python executable to use (default: python3)
  --prototype <path>     Path to pi-mono repository
  --skip-prototype-deps  Skip installing prototype requirements into the app venv
  --skip-frontend-deps   Skip installing frontend npm dependencies
  --help                 Show this help

What this script does:
  1. Creates .venv if needed
  2. Installs the Python app in editable mode
  3. Installs frontend npm dependencies unless skipped
  4. Installs prototype requirements into the same venv when available
  5. Creates or updates local .env defaults
  6. Generates a random SECRET_KEY if writing .env
  7. Defaults to SQLite for easiest first run
  8. Runs database migrations
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-env)
      FORCE_ENV_WRITE="true"
      shift
      ;;
    --python)
      shift
      [[ $# -gt 0 ]] || fail "missing value for --python"
      PYTHON_BIN="$1"
      shift
      ;;
    --prototype)
      shift
      [[ $# -gt 0 ]] || fail "missing value for --prototype"
      PROTOTYPE_REPO_PATH_DEFAULT="$1"
      shift
      ;;
    --skip-prototype-deps)
      SKIP_PROTOTYPE_DEPS="true"
      shift
      ;;
    --skip-frontend-deps)
      SKIP_FRONTEND_DEPS="true"
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

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_command "$PYTHON_BIN"
if [[ "$SKIP_FRONTEND_DEPS" != "true" ]]; then
  require_command npm
fi

PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PYTHON_VERSION" in
  3.11|3.12|3.13)
    ;;
  *)
    fail "Python 3.11+ is required, found ${PYTHON_VERSION}"
    ;;
esac

if [[ -z "$PROTOTYPE_REPO_PATH_DEFAULT" ]]; then
  if [[ -d "${ROOT_DIR}/../pi-mono" ]]; then
    PROTOTYPE_REPO_PATH_DEFAULT="$(cd "${ROOT_DIR}/../pi-mono" && pwd)"
  elif [[ -d "/home/aurelio/workspace/pi-mono" ]]; then
    PROTOTYPE_REPO_PATH_DEFAULT="/home/aurelio/workspace/pi-mono"
  fi
fi

log "repo root: ${ROOT_DIR}"
log "using python: ${PYTHON_BIN}"

if [[ ! -d "$VENV_DIR" ]]; then
  log "creating virtual environment"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  log "virtual environment already exists"
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

[[ -x "$VENV_PYTHON" ]] || fail "virtualenv python not found at ${VENV_PYTHON}"
[[ -x "$VENV_PIP" ]] || fail "virtualenv pip not found at ${VENV_PIP}"

if [[ -z "$PROTOTYPE_PYTHON_EXECUTABLE_DEFAULT" ]]; then
  PROTOTYPE_PYTHON_EXECUTABLE_DEFAULT="$VENV_PYTHON"
fi

log "installing project dependencies"
"$VENV_PIP" install -e "$ROOT_DIR[prototype]"

if [[ "$SKIP_FRONTEND_DEPS" == "true" ]]; then
  log "skipping frontend dependency installation"
elif [[ -d "$FRONTEND_DIR" ]]; then
  log "installing frontend dependencies"
  npm --prefix "$FRONTEND_DIR" install
else
  fail "missing frontend directory: ${FRONTEND_DIR}"
fi

PROTOTYPE_REQUIREMENTS_FILE=""
if [[ -n "$PROTOTYPE_REPO_PATH_DEFAULT" ]]; then
  candidate_requirements="${PROTOTYPE_REPO_PATH_DEFAULT}/.pi/skills/trade-proposer/requirements.txt"
  if [[ -f "$candidate_requirements" ]]; then
    PROTOTYPE_REQUIREMENTS_FILE="$candidate_requirements"
  fi
fi

if [[ "$SKIP_PROTOTYPE_DEPS" == "true" ]]; then
  log "skipping prototype dependency installation"
elif [[ -n "$PROTOTYPE_REQUIREMENTS_FILE" ]]; then
  log "installing prototype dependencies from ${PROTOTYPE_REQUIREMENTS_FILE}"
  "$VENV_PIP" install -r "$PROTOTYPE_REQUIREMENTS_FILE"
else
  log "prototype requirements file not found; skipping prototype dependency installation"
fi

write_env_file() {
  local secret_key
  secret_key="$($VENV_PYTHON -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > "$ENV_FILE" <<EOF
APP_NAME=Trade Proposer App
APP_ENV=development
APP_HOST=${APP_HOST}
APP_PORT=${APP_PORT}
DATABASE_URL=${DATABASE_URL_DEFAULT}
REDIS_URL=${REDIS_URL_DEFAULT}
SECRET_KEY=${secret_key}
PROTOTYPE_REPO_PATH=${PROTOTYPE_REPO_PATH_DEFAULT}
PROTOTYPE_PYTHON_EXECUTABLE=${PROTOTYPE_PYTHON_EXECUTABLE_DEFAULT}
SINGLE_USER_AUTH_ENABLED=true
SINGLE_USER_AUTH_TOKEN=change-me
SINGLE_USER_AUTH_ALLOWLIST_PATHS=/api/health,/api/health/preflight,/api/health/prototype
SINGLE_USER_AUTH_USERNAME=admin
SINGLE_USER_AUTH_PASSWORD=change-me
EOF
}

update_or_append_env_setting() {
  local key="$1"
  local value="$2"
  "$VENV_PYTHON" - <<PY
from pathlib import Path
key = ${1@Q}
value = ${2@Q}
path = Path(${ENV_FILE@Q})
content = path.read_text() if path.exists() else ""
lines = content.splitlines()
updated = []
found = False
for line in lines:
    if line.startswith(f"{key}="):
        updated.append(f"{key}={value}")
        found = True
    else:
        updated.append(line)
if not found:
    updated.append(f"{key}={value}")
path.write_text("\n".join(updated) + "\n")
PY
}

if [[ ! -f "$ENV_FILE" || "$FORCE_ENV_WRITE" == "true" ]]; then
  log "writing ${ENV_FILE}"
  write_env_file
else
  log ".env already exists, updating prototype defaults"
  update_or_append_env_setting "PROTOTYPE_REPO_PATH" "$PROTOTYPE_REPO_PATH_DEFAULT"
  update_or_append_env_setting "PROTOTYPE_PYTHON_EXECUTABLE" "$PROTOTYPE_PYTHON_EXECUTABLE_DEFAULT"
fi

[[ -f "$ENV_EXAMPLE_FILE" ]] || fail "missing ${ENV_EXAMPLE_FILE}"

log "running database migrations"
(
  cd "$ROOT_DIR"
  "$VENV_PYTHON" -m trade_proposer_app.migrations
)

MANUAL_TASKS=()
if [[ -z "$PROTOTYPE_REPO_PATH_DEFAULT" ]]; then
  MANUAL_TASKS+=("set PROTOTYPE_REPO_PATH in .env to your local pi-mono checkout")
elif [[ ! -f "${PROTOTYPE_REPO_PATH_DEFAULT}/.pi/skills/trade-proposer/scripts/propose_trade.py" ]]; then
  MANUAL_TASKS+=("verify PROTOTYPE_REPO_PATH in .env because the trade-proposer prototype script was not found there")
fi
if [[ -z "$PROTOTYPE_REQUIREMENTS_FILE" && "$SKIP_PROTOTYPE_DEPS" != "true" ]]; then
  MANUAL_TASKS+=("install prototype dependencies manually because .pi/skills/trade-proposer/requirements.txt was not found")
fi
if [[ "$SKIP_FRONTEND_DEPS" == "true" ]]; then
  MANUAL_TASKS+=("run npm --prefix frontend install before starting the React frontend")
fi

log "setup complete"
printf '\n'
printf 'Next command:\n'
printf '  ./scripts/start-dev.sh\n'
printf '\n'
printf 'Primary local URLs after startup:\n'
printf '  frontend: http://localhost:5173/\n'
printf '  api:      http://localhost:%s/api/health\n' "$APP_PORT"
printf '\n'

if [[ ${#MANUAL_TASKS[@]} -gt 0 ]]; then
  printf 'Manual tasks remaining:\n'
  for task in "${MANUAL_TASKS[@]}"; do
    printf '  - %s\n' "$task"
  done
  printf '\n'
else
  printf 'Manual tasks remaining:\n'
  printf '  - verify the prototype environment can run recommendation generation\n'
  printf '  - optionally add provider credentials in /settings\n'
  printf '\n'
fi
