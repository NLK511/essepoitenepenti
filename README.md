# Trade Proposer App

Trade Proposer App is a deployable application for systematic trade recommendation workflows. It provides a FastAPI backend, a React/Vite operator UI, and worker-backed execution. The recommendation pipeline runs entirely inside this repository: it fetches price history via `yfinance`, builds technical feature vectors with `pandas`, applies the bundled weights (`src/trade_proposer_app/data/weights.json`), ingests news via the native `NewsIngestionService`, reuses shared macro/industry sentiment snapshots, and emits directional/confidence/price outputs with auditable diagnostics.

## Core Features
- **Job Management**: Define scheduled or manual runs for proposal generation, evaluation, weight optimization, and sentiment snapshot refresh.
- **Traceability**: Full history of runs, recommendations, and shared sentiment snapshots with drill-down views and stored diagnostics.
- **Reliability**: Atomic run claiming, duplicate-run prevention, explicit degraded-state reporting, and snapshot freshness checks in health/preflight.
- **News-aware insights**: Native news ingestion pulls configured articles, derives sentiment, and stores both a digest and structured metadata. Operators can optionally route that digest through OpenAI or the `pi` CLI (configured via `/settings`) so richer narratives and enhanced sentiment metadata appear in detail views.
- **In-App Docs**: Integrated documentation browser for methodology and technical reference.

## Quick Start

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

- **Frontend**: `http://localhost:5173/`
- **API Health**: `http://localhost:8000/api/health`
- **Preflight**: `http://localhost:8000/api/health/preflight`

## Production deployment

For production-like launches use `./scripts/start-prod.sh`. The script reads your `.env`, builds the frontend with `npm run build`, runs any pending migrations, and then starts the FastAPI API (which serves the built SPA from `frontend/dist`) and the worker process together. Run it from the repo root after installing dependencies (the same setup process as development) and configuring secrets such as `SECRET_KEY`.

`start-prod.sh` exposes the API and frontend on `APP_HOST:APP_PORT` (defaults to `0.0.0.0:8000`). You can override those values on the command line with `--host` and `--port`, or leave them configured in `.env`. Example:

```bash
./scripts/start-prod.sh --host 0.0.0.0 --port 8000
```

If you build the frontend separately (with `npm ci` + `npm run build`) in your deployment pipeline, pass `--skip-frontend-build` so the script uses the existing `frontend/dist` assets instead of rebuilding.

After startup:

- Frontend & SPA routes: `http://<APP_HOST>:<APP_PORT>/`
- API health: `http://<APP_HOST>:<APP_PORT>/api/health`
- Preflight: `http://<APP_HOST>:<APP_PORT>/api/health/preflight`

## Documentation

For detailed information, see the `docs/` directory or browse them in-app at `/docs`:
- [Documentation Index](docs/docs-index.md)
- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Features & Capabilities](docs/features-and-capabilities.md)
- [Recommendation Methodology](docs/recommendation-methodology.md)
- [User Journeys](docs/user-journeys.md)
- [Product Thesis](docs/product-thesis.md)
- [Phase 2: App-native Outcomes](docs/phase-2-app-native.md)
- [Raw Details Reference](docs/raw-details-reference.md)

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy (SQLite/Postgres).
- **Frontend**: React, TypeScript, Vite.
- **Background**: Custom worker and scheduler.
- **Dependencies**: `pandas`, `yfinance`, and standard packages for the internal scoring pipeline.
