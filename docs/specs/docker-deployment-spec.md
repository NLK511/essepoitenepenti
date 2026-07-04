# Docker deployment spec

**Status:** target behavior

## Purpose

Add Docker Compose deployment as a parallel, optional deployment path for a small single-host installation.

This feature must not replace or weaken the current host-level startup/supervision flow. The existing `scripts/setup.sh`, `scripts/start-prod.sh`, `scripts/stop-prod.sh`, development scripts, and production supervision behavior remain supported and battle-tested while the Docker path is validated.

## Goals

- Run each long-lived app process in its own container:
  - API
  - worker
  - scheduler
  - Postgres
- Keep one Docker Compose file for this deployment path.
- Include Postgres in the same Compose stack because the intended deployment is small and single-host.
- Persist Postgres data across container rebuilds/restarts.
- Restart crashed containers automatically.
- Support multiple worker containers, defaulting to one worker.
- Keep exactly one scheduler by default and document that scheduler scaling is unsafe.
- Keep the current non-Docker startup/supervisor mechanism intact.
- Add app-level runtime supervision history using Postgres-backed heartbeats/lifecycle events.
- Persist worker log files to a host-mounted path readable by the API container so the authenticated Worker logs UI works in Docker without mounting the Docker socket.
- Keep a public minimal health endpoint safe for internet uptime monitoring.
- Keep detailed runtime/crash/restart history authenticated.

## Non-goals

- Do not replace `scripts/start-prod.sh` as the canonical production path until Docker has passed a separate soak/validation decision.
- Do not require separate dev/staging/prod Compose files.
- Do not add Docker Swarm/Kubernetes.
- Do not mount the Docker socket for crash detection in the first implementation.
- Do not send email alerts in the first implementation.
- Do not enable multiple schedulers.
- Do not enable multiple workers by default.
- Do not change broker safety gates, run leases, broker idempotency, circuit breakers, or halt semantics.

## Compose topology

The single Compose file should define at least these services:

### `postgres`

- Uses a pinned Postgres major version.
- Stores data in a named persistent volume.
- Has a healthcheck based on `pg_isready`.
- Does not expose port `5432` publicly by default.
- Uses non-default credentials from environment variables.

### `api`

- Runs only the FastAPI/uvicorn API process.
- Depends on healthy Postgres.
- Uses the production app image, not `pip install -e .` at startup.
- Exposes the configured HTTP port.
- Has a healthcheck that calls the minimal health endpoint.
- Uses `restart: unless-stopped`.

### `worker`

- Runs only `trade_proposer_app.workers.tasks`.
- Depends on healthy Postgres.
- Uses the same production app image as `api`.
- Uses `restart: unless-stopped`.
- Writes a per-worker log file under the shared `.prod-run/workers` mount using the runtime worker id.
- Supports scaling with Compose, for example:

```bash
docker compose up -d --scale worker=3
```

Constraints:

- The worker service must not set `container_name`, because that prevents scaling.
- The default deployment must run one worker.
- Multiple workers are allowed only after operator acknowledgement that broker/risk idempotency and job lease behavior are being intentionally exercised.

### `scheduler`

- Runs only `trade_proposer_app.scheduler`.
- Depends on healthy Postgres.
- Uses the same production app image as `api`.
- Uses `restart: unless-stopped`.
- Must not be scaled above one instance.

## Restart policy

Long-lived services should use:

```yaml
restart: unless-stopped
```

This applies to:

- `api`
- `worker`
- `scheduler`
- `postgres`

Semantics:

- restart after process crash
- restart after Docker daemon/host reboot
- remain stopped after an explicit operator stop

One-shot jobs, if added later, must use:

```yaml
restart: "no"
```

Examples:

- migration check
- backup
- restore smoke test
- production preflight

## Image/build requirements

The Docker deployment must use a built app image instead of installing the package on every container start.

Required behavior:

- `Dockerfile` installs Python dependencies at build time.
- frontend assets are built or copied in a deterministic way if the API serves frontend assets.
- runtime containers start directly with their process command.
- no source-code bind mount is required for the production-style Docker path.
- `.env.example` is not used as the runtime env file.

## Environment and secrets

The Compose stack should read deployment configuration from an operator-created env file or environment injection.

Required:

- no committed production secrets
- no default Postgres password in production instructions
- `DATABASE_URL` points to the Compose Postgres service
- app auth/session/encryption settings are explicit
- broker/provider credentials remain write-only/redacted through existing app mechanisms

Recommended local single-host pattern:

- `.env.docker` or `.env.prod.local` is created by the operator and excluded from git
- `POSTGRES_PASSWORD` is generated by the operator
- API is the only public port by default

## Postgres persistence, backup, and restore

Because Postgres is in the same Compose stack, backup/restore is mandatory production-readiness work.

Required:

- named volume for `/var/lib/postgresql/data`
- documented backup command using `pg_dump`
- documented restore procedure
- restore smoke test path that restores a backup into a temporary database/container and validates schema
- no deployment instructions that imply container recreation is enough for data safety

## Runtime supervision history: app-level option A

The first implementation must use app-level, Postgres-backed runtime supervision history. It must not depend on Docker socket events.

Each long-lived process should periodically write heartbeat/lifecycle evidence to Postgres.

Process identities should include:

- process role: `api`, `worker`, or `scheduler`
- instance id
- hostname/container hostname when available
- process id when available
- app version/code version when available
- started timestamp
- last heartbeat timestamp
- graceful shutdown timestamp when available
- status: `starting`, `healthy`, `stale`, `stopped`, or `unknown`

Lifecycle events should include:

- `process_started`
- `heartbeat_recorded` or compact heartbeat updates
- `graceful_shutdown`
- `stale_heartbeat_detected`
- `unclean_restart_inferred`

Unclean restart inference:

- when a process starts, it should inspect prior active process records for the same role/instance family
- if a prior process did not record graceful shutdown and its heartbeat is stale, persist `unclean_restart_inferred`
- exact Docker exit code is not required for this phase

Heartbeat stale thresholds should be configurable and conservative.

## Health endpoints

### Public minimal health

`GET /api/health` must remain safe for public internet uptime checks.

It should expose only minimal non-sensitive state, for example:

```json
{
  "status": "ok",
  "api": "ok",
  "database": "ok",
  "timestamp": "2026-07-02T00:00:00Z"
}
```

It must not expose:

- secrets
- stack traces
- broker account details
- provider credentials
- detailed crash history
- internal filesystem paths
- raw environment variables

### Authenticated detailed runtime health

Add or extend authenticated endpoints for detailed supervision history, for example:

- `GET /api/health/runtime`
- `GET /api/health/runtime/events`

Detailed runtime health may include:

- active API/worker/scheduler instances
- last heartbeat per instance
- stale process warnings
- inferred unclean restart count
- recent lifecycle events
- database connectivity details at safe granularity
- current broker halt state
- active circuit-breaker summary
- unresolved `needs_review` exposure count
- recent failed job count

Detailed endpoints must require the same authentication model as other operator/debug APIs.

## UI expectations

Operator-facing health/runtime UI should eventually show:

- API status
- scheduler status
- worker count and worker identities
- stale worker/scheduler warnings
- last start time per process
- inferred unclean restarts
- latest lifecycle events
- Postgres connectivity state
- broker halt/circuit-breaker summary

UI implementation is not required in the first Docker Compose slice if authenticated API endpoints expose the data clearly.

## Multiple worker support

Multiple workers are supported by configuration, not default behavior.

Rules:

- default worker replica count is one
- scaling workers must not scale scheduler
- worker service must be replica-safe at the container level
- job execution safety remains the responsibility of Postgres-backed leases/idempotency
- broker execution duplication must remain impossible through existing broker-order records, client ids, and reconciliation gates

Before recommending multiple workers operationally, validate:

- two workers racing for queued jobs
- broker submission idempotency under worker crash/restart
- provider rate-limit behavior
- long-running replay/tuning job contention
- worker identity visibility in runtime health

## Docker crash email alerts

Email-on-crash is not part of the first implementation.

Rationale:

- Docker Compose does not send email natively.
- SMTP alerting introduces extra secrets and delivery failure modes.
- Mounting the Docker socket for exact crash events increases host-level risk.
- Postgres-backed runtime history is more useful for operator diagnosis and works for both Docker and non-Docker startup paths.

Future email alerts may be added by consuming persisted runtime events instead of directly watching Docker, unless exact Docker exit codes become necessary.

## Compatibility with current startup/supervision

The existing startup flow remains valid:

- `scripts/setup.sh`
- `scripts/start-dev.sh`
- `scripts/start-prod.sh`
- `scripts/stop-prod.sh`

Docker deployment is additive.

`docs/specs/production-supervision-spec.md` remains the current contract for `scripts/start-prod.sh`. Docker-specific supervision behavior belongs in this spec until the Docker path becomes the preferred production path.

## Acceptance criteria

Docker deployment is acceptable when:

- `docker compose up -d` starts Postgres, API, one worker, and one scheduler.
- API health returns healthy after Postgres is ready.
- Worker and scheduler write runtime heartbeats.
- Restarting a worker container creates visible lifecycle history without taking down the API.
- Restarting scheduler creates visible lifecycle history and does not create duplicate scheduler instances.
- `docker compose up -d --scale worker=2` starts two workers and both are visible in runtime health.
- Postgres data survives container restart/recreate.
- Backup and restore-smoke commands are documented and tested.
- The current `scripts/start-prod.sh` path still works unchanged.
- Public `/api/health` is safe to expose to the internet.
- Detailed runtime history requires authentication.

## Implementation decisions

Initial decisions for the first implementation:

1. Docker env file: use `.env.docker`, created by the operator and excluded from git.
2. Frontend build: use the standard production Docker pattern: build frontend assets inside a multi-stage Docker image and copy the built assets into the final runtime image.
3. Heartbeat defaults: API, worker, and scheduler should heartbeat every 30 seconds; stale threshold should default to 90 seconds. These values should be configurable.
4. Lifecycle storage: reuse the existing `observability_events` table for lifecycle event history, and add a dedicated runtime-process/heartbeat table for active API/worker/scheduler state. The existing `worker_heartbeats` table is worker-specific and can inform the design, but it is not sufficient for API and scheduler state.
5. Public health: `/api/health` is the only public internet-facing health endpoint. Detailed runtime/preflight endpoints must remain authenticated or explicitly allowlisted only after a security review.
6. Backup files: use an operator-configurable host bind mount, defaulting to `./backups` for single-host deployments. This keeps backups easy to copy off-host and inspect without Docker volume tooling.

## Existing event/heartbeat storage

Current generic observability events are stored in `observability_events` with these fields:

- `id`
- `run_id`
- `job_id`
- `correlation_id`
- `event_type`
- `severity`
- `source`
- `message`
- `payload_json`
- `created_at`

This is suitable for append-only lifecycle events such as `process_started`, `stale_heartbeat_detected`, and `unclean_restart_inferred`.

Current worker heartbeat storage is in `worker_heartbeats` with these fields:

- `worker_id`
- `hostname`
- `pid`
- `status`
- `last_heartbeat_at`
- `started_at`
- `version`
- `active_run_id`
- `metadata_json`
- `created_at`
- `updated_at`

This is useful but worker-specific. Docker runtime supervision should introduce a role-neutral process heartbeat table rather than overloading worker-only semantics for API and scheduler.
