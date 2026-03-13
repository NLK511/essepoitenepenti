# Trade Proposer App

A lightweight, maintainable productization of the current trade proposer prototype.

This repository turns the current skill-based workflow into a deployable application with:
- a FastAPI JSON API
- a React/Vite frontend
- typed internal service contracts
- persisted runs and recommendations
- worker-backed execution flow
- clear module boundaries that can later evolve into microservices

## Current implementation status

Implemented now:
- FastAPI application exposing the product API
- React/Vite frontend consuming that API
- persisted watchlists
- persisted jobs
- persisted runs
- persisted recommendations
- queued run creation and worker processing
- run detail and debugger workflows
- history with filtering, sorting, and pagination
- operator settings UI
- searchable in-app docs browser
- encrypted-at-rest provider credential persistence
- prototype preflight checks in health and settings
- configurable LLM-backed news summary engine with `pi_agent` default and model selection
- migration scaffolding
- repository and route tests

Still not fully production-ready:
- scheduler correctness still needs hardening
- credential rotation is not implemented
- auth and tenancy are not implemented

## Product goals

- Turn the current script/dashboard prototype into a real server product.
- Keep the system lightweight and easy to operate on a single machine or small VPS.
- Preserve the existing skill boundaries as internal modules first.
- Make later service extraction possible without redesigning the domain.

## Principles

- Modular monolith first, microservices later.
- Python-first for backend/domain logic.
- Minimal frontend stack: React, React Router, Vite, no heavy client framework additions.
- Typed contracts between modules.
- Operational simplicity over premature distribution.
- Clear documentation and predictable user journeys.
- Never hide execution failures with synthetic fallback recommendations or dummy default values.

## Current architecture

Runtime components in the repo today:
- `api`: FastAPI JSON API and optional built-frontend asset serving
- `frontend`: React/Vite SPA for operators
- `worker`: queued run processor
- `scheduler`: scheduling entrypoint stub with enqueue behavior
- `sqlite`: default local persistence for lightweight startup

Target runtime components for deployment:
- `api`
- `frontend` assets served by the API or a reverse proxy
- `worker`
- `scheduler`
- `postgres`
- `redis`

## Repo layout

```text
trade-proposer-app/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── alembic/
├── docs/
├── frontend/
│   ├── package.json
│   ├── index.html
│   └── src/
├── scripts/
│   ├── setup.sh
│   ├── start-dev.sh
│   ├── stop-dev.sh
│   └── restart-dev.sh
├── src/trade_proposer_app/
│   ├── api/
│   ├── domain/
│   ├── persistence/
│   ├── repositories/
│   ├── services/
│   ├── web/
│   └── workers/
├── templates/
└── tests/
```

## Quick setup

For the easiest first local setup:

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

This now installs both:
- Python dependencies into `.venv`
- frontend npm dependencies into `frontend/node_modules`

Primary local URLs after startup:
- frontend: `http://localhost:5173/`
- docs browser: `http://localhost:5173/docs`
- API health: `http://localhost:8000/api/health`
- prototype preflight: `http://localhost:8000/api/health/prototype`

If prototype preflight is failed and you still want to force startup for debugging:

```bash
./scripts/start-dev.sh --allow-degraded-prototype
```

If you only want backend processes:

```bash
./scripts/start-dev.sh --backend-only
```

## Frontend notes

The UI is now a React/Vite application under `frontend/`.

Local development:
- Vite serves the SPA on port `5173`
- Vite proxies `/api` requests to the FastAPI app on port `8000`
- `scripts/start-dev.sh` starts API, worker, and frontend together

Production/static serving:
- build with `cd frontend && npm install && npm run build`
- FastAPI serves built assets from `frontend/dist` when present

The frontend intentionally stays small:
- React
- React Router
- TypeScript
- one shared stylesheet
- no client-side state management library
- no UI framework dependency

## Documentation

The app includes a searchable in-app docs browser at `/docs`.
It indexes `README.md` and all markdown files under `docs/`.

Important docs include:
- `docs/getting-started.md`
- `docs/architecture.md`
- `docs/status.md`
- `docs/features-and-capabilities.md`
- `docs/raw-details-reference.md`
- `docs/user-journeys.md`

## Summary engine and prototype integration

The summary engine is configurable from `/settings`:
- backend: `pi_agent` or `openai_api`
- model: free-form model id
- timeout/max tokens
- optional `PI_CODING_AGENT_DIR` override for pi-based summarization

Default behavior is `pi_agent`, which does not require an API key when pi is already authenticated for the current OS user.

Supported external news/social services used by the integrated prototype:
- Yahoo Finance: https://finance.yahoo.com/
- NewsAPI: https://newsapi.org/
- Alpha Vantage: https://www.alphavantage.co/
- Finnhub: https://finnhub.io/
- Alpaca News: https://alpaca.markets/
- Nitter instances: https://github.com/zedeus/nitter/wiki/Instances

## Read these first

- `docs/getting-started.md`
- `docs/product-plan.md`
- `docs/architecture.md`
- `docs/status.md`
- `docs/critical-review.md`
- `docs/features-and-capabilities.md`
- `docs/raw-details-reference.md`
- `docs/user-journeys.md`
- `docs/roadmap.md`
