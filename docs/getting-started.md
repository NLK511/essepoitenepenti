# Getting Started

Trade Proposer App is a FastAPI backend, a React/Vite frontend, and a worker process for queued runs. The recommendation pipeline now runs entirely within this repository: it uses pandas/yfinance to fetch and transform market data, applies the bundled `weights.json`, and emits recommendations without shelling out to the prototype workspace. This guide covers the fastest path to a working local install, how to verify that the environment is healthy, and what to check when runs fail.

The most important behaviors to keep in mind are simple: creating or executing a job enqueues a run, the worker must be running to process it, recommendation generation depends on the internal pipeline and its pandas/yfinance/weights dependencies, startup blocks on known-bad internal preflight unless you explicitly override it, and failed recommendation runs remain explicit failures rather than silently turning into fallback outputs.

## Prerequisites

Install Python 3.11+, `pip`, `venv`, Node.js, `npm`, and Git. The app now runs a self-contained pipeline that pulls price history via `yfinance` and computes features with `pandas`, so no prototype repository is required.

## Fastest first-time setup

Run:

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

`setup.sh` creates `.venv`, installs the Python project in editable mode, installs frontend dependencies in `frontend/`, optionally installs prototype requirements into the same environment when available for compatibility, creates or refreshes `.env`, generates a random `SECRET_KEY`, defaults the app to SQLite for local startup, and runs migrations.

`start-dev.sh` runs migrations again for safety, performs the internal pipeline preflight, refuses startup if the preflight fails unless you pass `--allow-degraded-preflight` (alias `--allow-degraded-prototype`), and starts the API, worker, and Vite frontend together.

Useful options:

```bash
./scripts/setup.sh --help
./scripts/setup.sh --prototype /absolute/path/to/pi-mono  # optional legacy path (not required to run the internal pipeline)
./scripts/setup.sh --python python3.12
./scripts/setup.sh --force-env
./scripts/setup.sh --skip-prototype-deps      # optional legacy flag
./scripts/setup.sh --skip-frontend-deps

./scripts/start-dev.sh --allow-degraded-preflight (alias: --allow-degraded-prototype)
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
- internal pipeline preflight: `http://localhost:8000/api/health/preflight`

A good first verification pass is:
1. open the frontend
2. open Settings and confirm the internal pipeline preflight is healthy
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

The app no longer requires the prototype repo, so you can keep its workspace separate or omit it entirely. If you do run the prototype for other reasons, install its requirements into whatever environment you use for that project.

A minimal local `.env` using SQLite looks like this:

```env
APP_NAME=Trade Proposer App
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./trade_proposer.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-this-with-a-long-random-secret
```

## Summary engine and external services

When providers are configured, the pipeline now assembles a short digest of the latest headlines alongside the sentiment context flags. Operators can leave the summary backend set to `news_digest` for this headline-only output, or switch to `openai_api` (OpenAI) or `pi_agent` (a local Pi CLI) so the same digest and a concise technical snapshot are sent to a supported LLM backend. The `/settings` form exposes the `pi` command, working directory, and optional CLI flags when `pi_agent` is selected, so the app can treat a vanilla Pi tool as any other LLM provider while keeping the summarizer logic inside this repo. The resulting narrative and any summarizer diagnostics are stored in `analysis_json`, while the digest remains available as the fallback text.

Supported external news services ingested directly by the app-native pipeline:
- NewsAPI: https://newsapi.org/
- Finnhub: https://finnhub.io/

Additional connectors (Yahoo Finance, Alpha Vantage, Alpaca News, Nitter, etc.) remain on the roadmap for future enrichment.

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

### `start-dev.sh` refuses to start because internal preflight failed
Inspect `/api/health/preflight`, rerun `./scripts/setup.sh`, fix the transactional dependencies (pandas, yfinance, weights.json), and rerun with `--allow-degraded-preflight` (or the legacy `--allow-degraded-prototype`) only until you confirm the internal pipeline can fetch OHLC history.

### The frontend does not start
Rerun `./scripts/setup.sh`, make sure Node.js and `npm` are installed, and confirm that `frontend/node_modules` exists.

### Runs stay queued
Make sure the worker is running. The simplest path is to use `./scripts/start-dev.sh`, which starts the API, worker, and frontend together.

### Runs fail immediately with a data dependency error
Verify that the internal pipeline can import `pandas` and `yfinance` from the activated `.venv`, ensure the machine has network access to the requested ticker, check that `src/trade_proposer_app/data/weights.json` exists and is readable, and confirm that the summary backend and provider credentials (if used later) are configured in Settings.
