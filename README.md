# Trade Proposer App

Trade Proposer App is a deployable application for systematic trade recommendation workflows. It provides a FastAPI backend, a React/Vite operator UI, and worker-backed execution.

## Core Features
- **Job Management**: Define scheduled or manual runs for proposal generation, evaluation, or weight optimization.
- **Traceability**: Full history of runs and recommendations with deep diagnostics and ticker-level drill-down.
- **Reliability**: Atomic run claiming, duplicate-run prevention, and honest failure reporting.
- **In-App Docs**: Integrated documentation browser for methodology and technical reference.

## Quick Start

```bash
./scripts/setup.sh
./scripts/start-dev.sh
```

- **Frontend**: `http://localhost:5173/`
- **API Health**: `http://localhost:8000/api/health`

## Documentation

For detailed information, see the `docs/` directory or browse them in-app at `/docs`:
- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Features & Capabilities](docs/features-and-capabilities.md)
- [Recommendation Methodology](docs/recommendation-methodology.md)
- [User Journeys](docs/user-journeys.md)

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy (SQLite/Postgres).
- **Frontend**: React, TypeScript, Vite.
- **Background**: Custom worker and scheduler.
- **Integration**: Integrated with the trade-proposer prototype.
