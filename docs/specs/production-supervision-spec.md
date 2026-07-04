# Production supervision spec

**Status:** implemented
**Last updated:** 2026-06-27

## Purpose

Production startup must keep the operator UI/API available when a background helper process fails. A worker crash is an incident, not a reason to make the whole app unreachable.

## Current implementation

This spec covers the host-level `scripts/start-prod.sh` supervisor. Optional Docker Compose deployment is additive and governed by `docker-deployment-spec.md`; it does not replace this implemented path.

`scripts/start-prod.sh` starts and supervises three processes:

- API (`uvicorn`)
- worker (`trade_proposer_app.workers.tasks`)
- scheduler (`trade_proposer_app.scheduler`)

The supervisor writes lifecycle evidence to `.prod-run/lifecycle-audit.log` and process ids to `.prod-run/*.pid`.

## Required behavior

- API exit remains fatal. If the API process exits unexpectedly, the supervisor must stop remaining children and exit non-zero.
- Worker exit is non-fatal to the API. If the worker process exits unexpectedly, the supervisor must:
  - log the incident to the lifecycle audit log,
  - restart the worker with a fresh worker id and fresh worker log file,
  - update `.prod-run/worker.pid` and `.prod-run/meta.env`,
  - keep API and scheduler running.
- Scheduler exit is non-fatal to the API. If the scheduler process exits unexpectedly, the supervisor must:
  - log the incident to the lifecycle audit log,
  - restart the scheduler,
  - update `.prod-run/scheduler.pid` and `.prod-run/meta.env`,
  - keep API and worker running.
- Restarts must be bounded to avoid an infinite crash loop. If worker or scheduler exits too many times inside the configured restart window, that helper is considered fatal and the supervisor may shut down the stack.
- The default restart policy is conservative:
  - max restarts: 5
  - restart window: 300 seconds
  - restart delay: 2 seconds
- Operators can override the policy with:
  - `PROD_SUPERVISOR_MAX_RESTARTS`
  - `PROD_SUPERVISOR_RESTART_WINDOW_SECONDS`
  - `PROD_SUPERVISOR_RESTART_DELAY_SECONDS`

## Out of scope

- Diagnosing the exact native/OS reason for a worker process disappearance.
- Replacing the shell supervisor with systemd, Docker, or another process manager.
