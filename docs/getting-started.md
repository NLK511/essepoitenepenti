# Getting Started

Trade Proposer App is a FastAPI backend, a React/Vite frontend, a worker process for queued runs, and a thin adapter around the existing prototype strategy in `pi-mono`. This guide covers the fastest path to a working local install, how to verify that the environment is healthy, and what to check when runs fail.

The most important behaviors to keep in mind are simple: creating or executing a job enqueues a run, the worker must be running to process it, recommendation generation depends on a correctly configured prototype environment, startup blocks on known-bad prototype preflight unless you explicitly override it, and failed recommendation runs remain explicit failures rather than silently turning into fallback outputs.

## Prerequisites

Install Python 3.11+, `pip`, `venv`, Node.js, `npm`, and Git. You also need access to the prototype repository because the app currently shells out to:

- `/home/aurelio/workspace/pi-mono/.pi/skills/trade-proposer/scripts/propose_trade.py`

## Fastest first-time setup

Run:

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

`setup.sh` creates `.venv`, installs the Python project in editable mode, installs frontend dependencies in `frontend/`, installs prototype requirements into the same environment when available, creates or refreshes `.env`, generates a random `SECRET_KEY`, defaults the app to SQLite for local startup, and runs migrations.

`start-dev.sh` runs migrations again for safety, performs prototype preflight, refuses startup if the prototype is already in a failed state unless you pass `--allow-degraded-prototype`, and starts the API, worker, and Vite frontend together.

Useful options:

```bash
./scripts/setup.sh --help
./scripts/setup.sh --prototype /absolute/path/to/pi-mono
./scripts/setup.sh --python python3.12
./scripts/setup.sh --force-env
./scripts/setup.sh --skip-prototype-deps
./scripts/setup.sh --skip-frontend-deps

./scripts/start-dev.sh --allow-degraded-prototype
./scripts/start-dev.sh --run-scheduler-once
./scripts/start-dev.sh --backend-only
./scripts/start-dev.sh --frontend-port 4173
./scripts/stop-dev.sh
./scripts/restart-dev.sh
```

## Local URLs and first verification

After startup, use:
- frontend UI: `http://localhost:5173/`
- docs browser: `http://localhost:5173/docs`
- API health: `http://localhost:8000/api/health`
- prototype preflight: `http://localhost:8000/api/health/prototype`

A good first verification pass is:
1. open the frontend
2. open Settings and confirm prototype preflight is healthy
3. review the summary backend, model, and prompt
4. create a watchlist
5. create a job
6. enqueue the job
7. confirm the worker processes the run
8. review the result in the dashboard, run detail, debugger, history, ticker page, and docs browser

## Frontend development model

The operator UI lives in `frontend/`. In development, Vite serves the SPA on port `5173` and proxies `/api` to FastAPI on port `8000`; normal local use therefore goes through `http://localhost:5173/`. If you build the frontend with `npm run build`, FastAPI serves assets from `frontend/dist` when those files exist.

## Manual environment setup

If you do not want to use the helper scripts:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
npm --prefix frontend install
```

If the prototype repo is present, install its requirements into the same environment:

```bash
pip install -r /absolute/path/to/pi-mono/.pi/skills/trade-proposer/requirements.txt
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
PROTOTYPE_REPO_PATH=/absolute/path/to/pi-mono
PROTOTYPE_PYTHON_EXECUTABLE=/absolute/path/to/trade-proposer-app/.venv/bin/python
```

## Summary engine and external services

The summary engine is configured from `/settings`. The default backend is `pi_agent`; `openai_api` is also supported. Operators can set the summary model, timeout, max tokens, and prompt. The default prompt asks the LLM to produce a very short summary focused on the day’s main event or events and the related industry and macro context.

Supported external news and social services used by the integrated prototype:
- Yahoo Finance: https://finance.yahoo.com/
- NewsAPI: https://newsapi.org/
- Alpha Vantage: https://www.alphavantage.co/
- Finnhub: https://finnhub.io/
- Alpaca News: https://alpaca.markets/
- Nitter instances: https://github.com/zedeus/nitter/wiki/Instances

For raw run and recommendation fields, see `docs/raw-details-reference.md`.

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

Frontend in a third terminal:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
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

### `start-dev.sh` refuses to start because prototype preflight failed
Inspect `/api/health/prototype`, rerun `./scripts/setup.sh`, fix the prototype environment, and use `--allow-degraded-prototype` only when you intentionally want to inspect a broken setup.

### The frontend does not start
Rerun `./scripts/setup.sh`, make sure Node.js and `npm` are installed, and confirm that `frontend/node_modules` exists.

### Runs stay queued
Make sure the worker is running. The simplest path is to use `./scripts/start-dev.sh`, which starts the API, worker, and frontend together.

### Runs fail immediately with a prototype dependency error
Verify `PROTOTYPE_REPO_PATH`, verify `PROTOTYPE_PYTHON_EXECUTABLE`, try the prototype script directly with `.venv/bin/python`, confirm the summary backend, model, and prompt in Settings, and then check the relevant provider credentials. If you use `pi_agent`, confirm that `pi` works for the app user. If you use `openai_api`, configure the `openai` credential in Settings.
