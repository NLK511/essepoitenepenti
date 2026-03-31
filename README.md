# Trade Proposer App

Trade Proposer App is a deployable application for systematic short-horizon trade planning workflows. It provides a FastAPI backend, a React/Vite operator UI, and worker-backed execution. The recommendation pipeline runs entirely inside this repository: it fetches price history via `yfinance`, builds technical feature vectors with `pandas`, applies the bundled weights (`src/trade_proposer_app/data/weights.json`), ingests news via the native `NewsIngestionService`, reuses shared macro/industry sentiment snapshots, and emits redesign-native ticker signals plus actionable `RecommendationPlan` outputs with auditable diagnostics. The taxonomy layer that feeds industry refresh and query generation now lives primarily under `src/trade_proposer_app/data/taxonomy/` as split ticker, industry, sector, relationship, and event-vocabulary files.

## Core Features
- **Job Management**: Define scheduled or manual runs for proposal generation, evaluation, weight optimization, and sentiment snapshot refresh.
- **Traceability**: Full history of runs, recommendation plans/outcomes, and shared sentiment snapshots with drill-down views and stored diagnostics.
- **Reliability**: Atomic run claiming, duplicate-run prevention, explicit degraded-state reporting, and snapshot freshness checks in health/preflight.
- **News-aware insights**: Native news ingestion pulls configured articles, derives sentiment, and stores both a digest and structured metadata. Operators can optionally route that digest through OpenAI or the `pi` CLI (configured via `/settings`) so richer narratives and enhanced sentiment metadata appear in detail views.
- **In-App Docs**: Integrated documentation browser for methodology and technical reference.

## Quick Start

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

SQLite remains the default local development database for the easiest first run. If you want a Postgres-backed local environment, start local services with `docker compose up -d postgres redis` and run `./scripts/setup.sh --force-env --database postgres`.

Useful setup options:
- `./scripts/setup.sh --with-dev-deps`
- `./scripts/setup.sh --with-openai`
- `./scripts/setup.sh --skip-frontend-deps`
- `./scripts/setup.sh --database postgres`

- **Frontend**: `http://localhost:5173/`
- **API Health**: `http://localhost:8000/api/health`
- **Preflight**: `http://localhost:8000/api/health/preflight`

## Database and migration notes

Current behavior:
- SQLite is the default local development database
- Postgres is supported for production-like local runs and deployment
- the Python dependency set now includes `psycopg[binary]` so Postgres URLs work without extra manual driver installation
- startup scripts now perform a friendlier connectivity check when `DATABASE_URL` points at Postgres
- Alembic revision ids were shortened to stay within Postgres `alembic_version.version_num` limits, and the migration entrypoint normalizes older stored revision ids automatically

Database references:
- current ER diagram: `docs/er-model.md`
- migration entrypoint: `python -m trade_proposer_app.migrations`
- generated local environment template: `.env.example`

## Postgres integration test

The repo now includes an optional Postgres migration smoke test:
- test file: `tests/test_postgres_integration.py`
- required env var: `POSTGRES_TEST_DATABASE_URL`

Run it locally with something like:

```bash
docker compose up -d postgres
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trade_proposer_test \
  .venv/bin/python -m unittest tests.test_postgres_integration -v
```

GitHub workflow:
- workflow file: `.github/workflows/postgres-integration.yml`
- status: kept in the repo but not enabled for automatic runs
- trigger mode: manual `workflow_dispatch` only

## Production deployment

For production-like launches use `./scripts/start-prod.sh`. The script reads your `.env`, builds the frontend with `npm run build`, runs any pending migrations, runs preflight, and then starts the FastAPI API (which serves the built SPA from `frontend/dist`), the worker, and the scheduler together. Run it from the repo root after installing dependencies (the same setup process as development) and configuring secrets such as `SECRET_KEY`.

`start-prod.sh` exposes the API and frontend on `APP_HOST:APP_PORT` (defaults to `0.0.0.0:8000`). You can override those values on the command line with `--host` and `--port`, or leave them configured in `.env`. Example:

```bash
./scripts/start-prod.sh --host 0.0.0.0 --port 8000
```

Stop production-style local processes with:

```bash
./scripts/stop-prod.sh
```

If you build the frontend separately (with `npm ci` + `npm run build`) in your deployment pipeline, pass `--skip-frontend-build` so the script uses the existing `frontend/dist` assets instead of rebuilding. If preflight is expected to be degraded during a temporary rollout, you can also pass `--allow-degraded-preflight`.

After startup:

- Frontend & SPA routes: `http://<APP_HOST>:<APP_PORT>/`
- API health: `http://<APP_HOST>:<APP_PORT>/api/health`
- Preflight: `http://<APP_HOST>:<APP_PORT>/api/health/preflight`

## Documentation

For detailed information, see the `docs/` directory or browse them in-app at `/docs`.

Suggested reading order:
- [Documentation Index](docs/docs-index.md)
- [Getting Started](docs/getting-started.md)
- [Operator Page & Field Guide](docs/operator-page-field-guide.md)
- [Glossary](docs/glossary.md)

Canonical current-state docs:
- [Product Thesis](docs/product-thesis.md)
- [Features & Capabilities](docs/features-and-capabilities.md)
- [Recommendation Methodology](docs/recommendation-methodology.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Raw Details Reference](docs/raw-details-reference.md)

Historical and archived material is now grouped under `docs/archive/` so it does not clutter the main reading path.

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy (SQLite by default for local dev, Postgres supported).
- **Frontend**: React, TypeScript, Vite.
- **Background**: Custom worker and scheduler.
- **Dependencies**: `pandas`, `yfinance`, and standard packages for the internal scoring pipeline.
