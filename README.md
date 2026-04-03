# Trade Proposer App

Trade Proposer App is a deployable short-horizon trade-planning application.

It combines:
- a FastAPI backend
- a React/Vite operator UI
- a worker and scheduler for background runs

The recommendation pipeline runs inside this repository. It ingests market/news data, builds features, applies the bundled weights, reuses shared macro and industry context, and emits ticker signals plus `RecommendationPlan` outputs with stored diagnostics.

## Core capabilities
- **Unified run system** for proposal generation, evaluation, optimization, and context refresh
- **Operator review flow** for runs, signals, plans, outcomes, and degraded states
- **Shared context reuse** across proposal and review workflows
- **Auditable diagnostics** stored with runs and recommendation objects
- **In-app docs** for product, methodology, and technical reference

## Quick start

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

Default local setup uses SQLite.

For a Postgres-backed local environment:

```bash
docker compose up -d postgres redis
./scripts/setup.sh --force-env --database postgres
```

Useful setup options:
- `./scripts/setup.sh --with-dev-deps`
- `./scripts/setup.sh --with-openai`
- `./scripts/setup.sh --skip-frontend-deps`
- `./scripts/setup.sh --database postgres`

Local URLs:
- frontend: `http://localhost:5173/`
- API health: `http://localhost:8000/api/health`
- preflight: `http://localhost:8000/api/health/preflight`

For full setup and troubleshooting, see `docs/getting-started.md`.

## Database and migrations

Current behavior:
- SQLite is the default local database
- Postgres is supported for production-like local runs and deployment
- `psycopg[binary]` is included, so Postgres URLs work without extra driver setup
- startup scripts perform friendlier connectivity checks for Postgres
- the migration entrypoint normalizes older Alembic revision ids automatically

References:
- ER model: `docs/er-model.md`
- migration entrypoint: `python -m trade_proposer_app.migrations`
- environment template: `.env.example`

## Optional Postgres integration test

- test file: `tests/test_postgres_integration.py`
- required env var: `POSTGRES_TEST_DATABASE_URL`

Example:

```bash
docker compose up -d postgres
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/trade_proposer_test \
  .venv/bin/python -m unittest tests.test_postgres_integration -v
```

GitHub workflow:
- file: `.github/workflows/postgres-integration.yml`
- trigger: manual `workflow_dispatch`

## Production-style local launch

Use `./scripts/start-prod.sh`.

It:
- reads `.env`
- builds the frontend
- runs pending migrations
- runs preflight
- starts the API, worker, and scheduler

Example:

```bash
./scripts/start-prod.sh --host 0.0.0.0 --port 8000
```

Stop with:

```bash
./scripts/stop-prod.sh
```

Useful flags:
- `--skip-frontend-build`
- `--allow-degraded-preflight`

## Documentation

Read docs in `docs/` or in-app at `/docs`.

Recommended starting points:
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

Historical material lives under `docs/archive/`.

## Tech stack
- **Backend**: Python, FastAPI, SQLAlchemy
- **Frontend**: React, TypeScript, Vite
- **Background**: custom worker and scheduler
- **Core data/scoring libs**: `pandas`, `yfinance`
