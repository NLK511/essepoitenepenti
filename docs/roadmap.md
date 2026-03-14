# Roadmap

## Current Status
Trade Proposer App is a functional foundation with:
- **Persistent State**: Watchlists, jobs, runs, recommendations, and settings.
- **Operator UI**: React/Vite SPA with dashboard, history, debugger, and docs.
- **Execution Model**: Worker-backed queue for background runs.
- **Workflow Types**: Support for proposal generation, evaluation, and weight optimization.
- **Reliability**: Honest failure handling, duplicate-run prevention, and encrypted credentials.

## Future Roadmap

### Phase 1: Operational Hardening (Immediate)
Focus on making the system more robust for continuous operation.
- **Scheduler Correctness**: Full cron support and enhanced concurrency guarantees.
- **Structured Prototype Contract**: Move away from stdout parsing to machine-readable JSON interfaces.
- **Worker Reliability**: Atomic run claiming and improved crash recovery.
- **Diagnostics**: Categorized and normalized diagnostics for better filtering and grouped analysis.

### Phase 2: Product Independence
Reduce reliance on external prototype state.
- **App-Native Outcomes**: Implement internal recommendation evaluation storage.
- **Provenance Tracking**: Audit trails for outcome updates (manual vs. automated).
- **Multi-ticker Policy**: Explicit handling of partial success/failure in multi-ticker runs.

### Phase 3: Security & Production Readiness
Prepare for real-world deployment beyond local use.
- **Credential Lifecycle**: Key rotation, re-encryption workflows, and external secret backend support.
- **Authentication**: Lightweight single-user auth baseline.
- **Observability**: Structured logging with run-level correlation and system health heartbeats.

### Phase 4: Expansion (Lower Priority)
- **Exporting**: Reporting and data export for historical runs.
- **Retry Logic**: Dead-letter queues and automated retries for transient failures.
- **Service Extraction**: Optional separation of ingestion or analysis into independent services.

## Related Docs
- `architecture.md`: System design and component boundaries.
- `getting-started.md`: Setup and local development guide.
- `features-and-capabilities.md`: Detailed product feature list.
