# Getting Started

**Status:** canonical setup and operations guide

This guide covers local setup, startup, and the first checks to run when something looks wrong.

The app has four main pieces:
- FastAPI backend
- React/Vite frontend
- worker
- scheduler

## What to remember

A few behaviors define the product:
- creating or executing a job enqueues a run
- the worker must be running for queued runs to complete
- the scheduler must be running for scheduled jobs to enqueue automatically
- startup blocks on known-bad preflight unless you explicitly override it
- missing inputs should become explicit warnings or neutral outputs, not hidden fallbacks

## Prerequisites

Install:
- Python 3.11+
- `pip`
- `venv`
- Node.js
- `npm`
- Git

No external prototype repository is required.

## Fastest first-time setup

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

What these scripts do:
- `setup.sh`
  - creates `.venv`
  - installs the Python project in editable mode
  - optionally installs dev and OpenAI extras
  - installs frontend dependencies in `frontend/`
  - creates or refreshes `.env`
  - generates a random `SECRET_KEY`
  - defaults local startup to SQLite
  - runs migrations
- `start-dev.sh`
  - runs migrations again for safety
  - performs the internal preflight check
  - refuses startup if preflight fails unless you pass `--allow-degraded-preflight`
  - starts API, worker, scheduler, and Vite together

Useful options:

```bash
./scripts/setup.sh --help
./scripts/setup.sh --python python3.12
./scripts/setup.sh --force-env
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
- frontend UI: `http://localhost:5173/`
- docs browser: `http://localhost:5173/docs`
- API health: `http://localhost:8000/api/health`
- preflight: `http://localhost:8000/api/health/preflight`

## First verification

A good first pass is:
1. open the frontend
2. open Settings and confirm preflight is healthy
3. confirm the summary backend configuration
4. create a watchlist
5. create a proposal job
6. run the job
7. confirm the worker processes the run
8. review the result in dashboard, run detail, recommendation plans, and ticker drill-downs
9. open the sentiment page and confirm shared snapshots are present or clearly marked stale/missing

## Frontend development model

The operator UI lives in `frontend/`. In development, Vite serves the SPA on port `5173` and proxies `/api` to FastAPI on port `8000`. If you build the frontend with `npm run build`, FastAPI serves assets from `frontend/dist` when those files exist.

## Manual environment setup

If you do not want to use the helper scripts:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
npm --prefix frontend install
```

A minimal local `.env` using SQLite looks like this:

```env
APP_NAME=Trade Proposer App
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./trade_proposer.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-this-with-a-long-random-secret
SINGLE_USER_AUTH_ENABLED=true
SINGLE_USER_AUTH_TOKEN=
SINGLE_USER_AUTH_ALLOWLIST_PATHS=/api/health,/api/health/preflight,/api/health/prototype
SINGLE_USER_AUTH_USERNAME=admin
SINGLE_USER_AUTH_PASSWORD=change-me
```

## Single-user authentication

Authentication is enabled by default (`SINGLE_USER_AUTH_ENABLED=true`).

You should:
- set `SINGLE_USER_AUTH_TOKEN` to a strong secret
- update `SINGLE_USER_AUTH_USERNAME` / `SINGLE_USER_AUTH_PASSWORD`

Every `/api` request must carry `Authorization: Bearer <token>`, except for allowlisted paths such as:
- `/api/health`
- `/api/health/preflight`
- `/api/health/prototype`
- `/api/login`

The React UI routes unauthenticated visitors to `/login`. The login page exchanges the configured username/password for the same bearer token and stores it locally for future API requests.

When using Vite manually, make sure `VITE_API_AUTH_TOKEN` matches `SINGLE_USER_AUTH_TOKEN`.

## Summary engine and external services

The app can keep summaries in digest-only mode or route them through:
- `openai_api` (install optional support with `./scripts/setup.sh --with-openai`)
- `pi_agent`

The resulting narrative, metadata, and any errors are stored in `analysis_json.summary`.

Supported external news services currently ingested by the app-native pipeline:
- NewsAPI: https://newsapi.org/
- Finnhub: https://finnhub.io/

Weight optimization also runs entirely inside the app and stores backup metadata for rollback.

For stored fields and diagnostics, see `raw-details-reference.md`.

## Manual startup without helper scripts

Backend:

```bash
source .venv/bin/activate
python -m trade_proposer_app.migrations
uvicorn trade_proposer_app.app:app --host 0.0.0.0 --port 8000
```

Worker in a second terminal:

```bash
source .venv/bin/activate
python -m trade_proposer_app.workers.tasks
```

Scheduler in a third terminal:

```bash
source .venv/bin/activate
python -m trade_proposer_app.scheduler
```

Frontend in a fourth terminal:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

Production-style local stop helper:

```bash
./scripts/stop-prod.sh
```

## Validation

Backend:

```bash
python3 -m compileall src tests alembic
.venv/bin/python -m unittest discover -s tests -v
```

Frontend:

```bash
npm --prefix frontend run check
```

## Common first-run issues

### `start-dev.sh` refuses to start because preflight failed
Inspect `/api/health/preflight`, rerun `./scripts/setup.sh`, and fix dependency issues. Use `--allow-degraded-preflight` only as a temporary override.

### Runs stay queued
Make sure the worker is running. If jobs are scheduled but never appear, make sure the scheduler is running too.

### Runs fail immediately with a data dependency error
Verify that:
- `pandas` and `yfinance` import correctly from `.venv`
- the machine has network access for market/news lookups
- `src/trade_proposer_app/data/weights.json` exists and is readable
- provider credentials are configured if you enabled external services

### Health is green but proposals still look degraded
Check the snapshot freshness warnings in `/api/health` or the Settings page. Proposal generation can still run when shared macro or industry snapshots are stale, but the app should tell you that sentiment context is degraded.

## See also

- `operator-page-field-guide.md` — where to go in the UI after startup
- `glossary.md` — shared terms used across the app
- `roadmap.md` — what is still being improved
