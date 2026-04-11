# Getting Started

**Status:** canonical setup and operations guide

This guide covers local setup, startup, and the first checks to run.

The app has four main parts:
- FastAPI backend
- React/Vite frontend
- worker
- scheduler

## What to remember

A few rules explain most first-run behavior:
- creating or executing a job enqueues a run
- the worker must be running for queued runs to finish
- the scheduler must be running for scheduled jobs to enqueue automatically
- startup blocks on failed preflight unless you explicitly override it
- missing inputs should appear as warnings or neutral outputs, not hidden fallbacks

## Prerequisites

Install:
- Python 3.11+
- `pip`
- `venv`
- Node.js
- `npm`
- Git

## Fastest setup

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

What these scripts do:
- `setup.sh`
  - creates `.venv`
  - installs backend and frontend dependencies
  - creates or refreshes `.env`
  - generates a `SECRET_KEY`
  - defaults to SQLite
  - runs migrations
- `start-dev.sh`
  - runs migrations again
  - runs preflight
  - starts API, worker, scheduler, and Vite

Useful options:

```bash
./scripts/setup.sh --help
./scripts/setup.sh --python python3.12
./scripts/setup.sh --force-env
./scripts/setup.sh --database sqlite
./scripts/setup.sh --database postgres
./scripts/setup.sh --skip-frontend-deps
./scripts/setup.sh --with-dev-deps
./scripts/setup.sh --with-openai

./scripts/start-dev.sh --allow-degraded-preflight
./scripts/start-dev.sh --run-scheduler-once
./scripts/start-dev.sh --backend-only
./scripts/start-dev.sh --frontend-port 4173
./scripts/stop-dev.sh
./scripts/restart-dev.sh
```

## Local URLs

After startup:
- frontend: `http://localhost:5173/`
- docs: `http://localhost:5173/docs`
- API health: `http://localhost:8000/api/health`
- preflight: `http://localhost:8000/api/health/preflight`

## First verification

A good first check is:
1. open the frontend
2. open Settings and confirm preflight is healthy
3. create a watchlist
4. create and run a proposal job
5. confirm the worker processes the run
6. review the result in dashboard, run detail, recommendation plans, and ticker pages
7. open Context and confirm shared context is present or clearly marked stale/missing

## Frontend development model

The UI lives in `frontend/`.

In development:
- Vite serves the SPA on port `5173`
- `/api` is proxied to FastAPI on port `8000`

If you build the frontend, FastAPI can serve assets from `frontend/dist`.

## Manual setup

If you do not want to use the helper scripts:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
npm --prefix frontend install
```

A minimal SQLite `.env`:

```env
APP_NAME=Trade Proposer App
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./trade_proposer.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-this-with-a-long-random-secret
WEIGHTS_FILE_PATH=
SINGLE_USER_AUTH_ENABLED=true
SINGLE_USER_AUTH_TOKEN=
SINGLE_USER_AUTH_ALLOWLIST_PATHS=/api/health,/api/health/preflight
SINGLE_USER_AUTH_USERNAME=admin
SINGLE_USER_AUTH_PASSWORD=change-me
```

For a Postgres-backed local setup:

```bash
docker compose up -d postgres redis
```

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trade_proposer
```

`WEIGHTS_FILE_PATH` is optional. Leave it blank to use the default bundled file.

## Authentication

Single-user authentication is enabled by default.

You should:
- set `SINGLE_USER_AUTH_TOKEN` to a strong secret
- change `SINGLE_USER_AUTH_USERNAME` and `SINGLE_USER_AUTH_PASSWORD`

Most `/api` requests require:

```text
Authorization: Bearer <token>
```

Common allowlisted paths:
- `/api/health`
- `/api/health/preflight`
- `/api/login`

The frontend uses a login page and stores the bearer token locally.

## Summaries and external services

The app can keep summaries in digest-only mode or route them through:
- `openai_api`
- `pi_agent`

The result is stored in `analysis_json.summary`.

Current news sources used by the app-native pipeline include:
- Google News RSS
- Yahoo Finance
- Finnhub
- NewsAPI, disabled by default on the free plan

For stored fields and diagnostics, see `raw-details-reference.md`.

## Manual startup

Backend:

```bash
source .venv/bin/activate
python -m trade_proposer_app.migrations
uvicorn trade_proposer_app.app:app --host 0.0.0.0 --port 8000
```

Worker:

```bash
source .venv/bin/activate
python -m trade_proposer_app.workers.tasks
```

Scheduler:

```bash
source .venv/bin/activate
python -m trade_proposer_app.scheduler
```

Frontend:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

## Seed default watchlists

To load the curated default watchlist pack:

```bash
.venv/bin/python scripts/deploy_watchlists.py
```

This seeds:
- 15 watchlists
- 18 scheduled `Auto: ...` jobs
- 750 equities across U.S., Europe, and Asia-Pacific groups

See `default-watchlists.md` for rationale.

## Validation

Backend:

```bash
python3 -m compileall src tests alembic
.venv/bin/python -m unittest discover -s tests -v
```

Optional Postgres migration test:

```bash
docker compose up -d postgres
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trade_proposer_test \
  .venv/bin/python -m unittest tests.test_postgres_integration -v
```

Frontend:

```bash
npm --prefix frontend run check
```

The repo also includes `.github/workflows/postgres-integration.yml`, kept for manual `workflow_dispatch` runs.

## Common first-run issues

### Cannot connect to PostgreSQL
If you selected Postgres, start local services first:

```bash
docker compose up -d postgres redis
```

If you want the easiest local setup instead:

```bash
./scripts/setup.sh --force-env --database sqlite
```

### `start-dev.sh` refuses to start
Inspect `/api/health/preflight`, rerun `./scripts/setup.sh`, and fix dependency issues. Use `--allow-degraded-preflight` only as a temporary override.

### Runs stay queued
Make sure the worker is running. If scheduled jobs never enqueue, make sure the scheduler is running too.

### Runs fail immediately with a data dependency error
Verify that:
- `pandas` and `yfinance` import from `.venv`
- the machine has network access
- `src/trade_proposer_app/data/weights.json` exists and is readable
- provider credentials are configured if needed

### Health is green but proposals still look degraded
Check freshness warnings in `/api/health` or Settings. Proposal generation can still run with stale shared context, but the app should show that degradation clearly.

## See also

- `operator-page-field-guide.md` — where to go in the UI after startup
- `glossary.md` — shared terms used across the app
- `roadmap.md` — current priorities
