# Docker deployment implementation checklist

**Status:** implemented; Docker soak remains pending

## Protocol

This work follows the Aurelio development protocol:

- specs are the source of truth
- update specs before behavior changes
- translate specs into detailed tests before implementation
- do not change tests to match code behavior unless the spec changes or the test is proven wrong
- keep the existing host-level startup/supervision path working throughout
- run focused tests for each slice and broader validation before declaring completion

Canonical spec: `specs/docker-deployment-spec.md`.

## Goal

Add Docker Compose deployment as an optional, parallel single-host deployment path without replacing the current `scripts/start-prod.sh` supervisor.

The first completed slice should allow an operator to run:

```bash
docker compose up -d
```

and get:

- Postgres with persistent data
- API container
- one worker container by default
- one scheduler container
- automatic container restart on crash
- public minimal `/api/health`
- authenticated runtime supervision history
- documented backup/restore commands

## Non-negotiable safety constraints

- Existing `scripts/start-prod.sh` and `scripts/stop-prod.sh` behavior must remain unchanged.
- Scheduler must remain single-instance.
- Worker scaling must default to one worker.
- Multiple workers must be supported by Compose but treated as an intentional operator action.
- Docker restart must not bypass broker halts, circuit breakers, reconciliation, leases, or idempotency.
- Public health must not expose detailed runtime, broker, provider, filesystem, stack-trace, or secret data.
- Detailed runtime/preflight data must require authentication.
- Postgres must be the deployment database target.

## Phase 0 — Spec and doc alignment

- [x] Create `docs/specs/docker-deployment-spec.md`.
- [x] Add Docker deployment spec to `docs/docs-index.md`.
- [x] Record implementation decisions:
  - `.env.docker`
  - multi-stage frontend build in Docker image
  - heartbeat every 30 seconds, stale after 90 seconds
  - reuse `observability_events` for lifecycle events
  - add role-neutral runtime-process heartbeat table
  - public `/api/health`, authenticated detailed runtime endpoints
  - host bind mount backups, default `./backups`
- [ ] Review `docs/specs/production-supervision-spec.md` and add a short note that Docker deployment is an additive alternate path governed by `docker-deployment-spec.md`, while `start-prod.sh` remains implemented/current.
- [ ] Update `docs/production-readiness-plan.md` to reference Docker deployment as an optional single-host deployment track, not a replacement for current production startup.

## Phase 1 — Runtime supervision tests first

Create tests before implementing runtime supervision plumbing.

### Model/repository tests

- [ ] Add tests for a role-neutral runtime process heartbeat repository:
  - creates API process heartbeat
  - creates worker process heartbeat
  - creates scheduler process heartbeat
  - updates `last_heartbeat_at`
  - records `started_at`, `hostname`, `pid`, `instance_id`, `role`, `status`, and metadata
  - lists active processes by stale threshold
  - marks stale processes without deleting history
  - does not expose secrets from metadata

### Lifecycle event tests

- [ ] Add tests proving lifecycle events are persisted to `observability_events`:
  - `process_started`
  - `graceful_shutdown`
  - `stale_heartbeat_detected`
  - `unclean_restart_inferred`
- [ ] Add tests for event payload shape:
  - process role
  - instance id
  - hostname
  - pid
  - previous process id when applicable
  - stale age when applicable
  - source set to runtime/supervision-specific value

### Unclean restart inference tests

- [ ] Add tests proving a new process start infers an unclean restart when:
  - previous same-role process has stale heartbeat
  - previous process has no graceful shutdown
- [ ] Add tests proving no unclean restart is inferred when:
  - previous process shut down gracefully
  - previous heartbeat is still fresh
  - previous process role is different

## Phase 2 — Runtime supervision implementation

- [ ] Add database migration for role-neutral runtime process table.
- [ ] Add persistence model for runtime process heartbeats.
- [ ] Add domain model for runtime process state.
- [ ] Add repository for create/update/list/stale runtime process records.
- [ ] Add runtime supervision service:
  - register process start
  - heartbeat process
  - record graceful shutdown
  - infer unclean restart
  - detect stale process records
- [ ] Reuse `ObservabilityEventRepository` for lifecycle event history.
- [ ] Keep existing `worker_heartbeats` behavior intact for current worker/run accounting.
- [ ] Add API process heartbeat on startup.
- [ ] Add scheduler process heartbeat loop.
- [ ] Add worker process heartbeat integration without breaking existing worker heartbeat behavior.
- [ ] Add graceful shutdown hooks where practical.

## Phase 3 — Health API tests first

- [ ] Add tests for public `GET /api/health`:
  - returns minimal safe payload
  - includes API/database/timestamp/status only or equivalent safe fields
  - does not include runtime event history
  - does not include broker/provider/account details
  - does not include environment variables, filesystem paths, or stack traces
- [ ] Add tests for authenticated detailed runtime endpoint, e.g. `GET /api/health/runtime`:
  - requires auth
  - lists active API/worker/scheduler state
  - reports stale process warnings
  - includes inferred unclean restart counts
  - includes safe broker halt/circuit-breaker summary if included
- [ ] Add tests for authenticated runtime events endpoint, e.g. `GET /api/health/runtime/events`:
  - requires auth
  - returns recent lifecycle events
  - supports limit/filter behavior if implemented
  - redacts unsafe payload fields

## Phase 4 — Health API implementation

- [ ] Keep `/api/health` public and minimal.
- [ ] Add/extend authenticated runtime health route.
- [ ] Add/extend authenticated runtime events route.
- [ ] Ensure auth allowlist does not accidentally expose detailed runtime/preflight routes.
- [ ] Add response models where useful.
- [ ] Add operator-safe summaries for:
  - process roles
  - instance ids
  - heartbeat ages
  - stale status
  - inferred restart history

## Phase 5 — Docker image and Compose tests/checks first

- [ ] Add a test or validation script that checks Docker files exist and contain required service names.
- [ ] Add a static validation test for Compose invariants:
  - services: `postgres`, `api`, `worker`, `scheduler`
  - `restart: unless-stopped` on long-lived services
  - no `container_name` on `worker`
  - scheduler not configured for replicas > 1
  - Postgres has a persistent volume
  - Postgres has healthcheck
  - API has healthcheck
  - Postgres port is not publicly exposed by default
- [ ] Add a Docker smoke-test script outline that can be run manually/CI when Docker is available.

## Phase 6 — Docker image and Compose implementation

- [ ] Add `.dockerignore`.
- [ ] Add multi-stage `Dockerfile`:
  - Python dependency install at build time
  - frontend build stage using standard Node tooling
  - final runtime image with app and built frontend assets
  - non-root runtime user if practical
  - no dev bind mount requirement
- [ ] Update single `docker-compose.yml` or adapt existing file to support production-style single-host deployment:
  - `postgres`
  - `api`
  - `worker`
  - `scheduler`
  - named Postgres data volume
  - backup bind mount defaulting to `./backups`
  - `.env.docker` env file
  - Postgres healthcheck
  - API healthcheck
  - `restart: unless-stopped`
- [ ] Preserve worker scaling support:

```bash
docker compose up -d --scale worker=3
```

- [ ] Document that scheduler must not be scaled.
- [ ] Remove production-style startup-time `pip install -e .` from Docker commands.
- [ ] Keep existing local/non-Docker scripts unchanged.

## Phase 7 — Docker operator scripts

Add small wrappers only if they reduce operator mistakes.

- [ ] Add `scripts/docker-up.sh` or equivalent.
- [ ] Add `scripts/docker-down.sh` or equivalent.
- [ ] Add `scripts/docker-logs.sh` or equivalent.
- [ ] Add `scripts/docker-backup.sh` using `pg_dump`.
- [ ] Add `scripts/docker-restore-smoke.sh` restoring into a temporary database/container and validating schema.
- [ ] Ensure scripts use Postgres and never silently fall back to SQLite.

## Phase 8 — Backup/restore tests and docs

- [ ] Add docs for backup location, default `./backups`.
- [ ] Add docs for creating a backup.
- [ ] Add docs for copying backups off-host.
- [ ] Add docs for restore smoke test.
- [ ] Add docs for full restore after data loss.
- [ ] Validate backup/restore commands against the Compose Postgres service.

## Phase 9 — Multi-worker validation

Default remains one worker. This phase proves optional scaling is visible and not obviously unsafe.

- [ ] Start Compose stack with default one worker and verify runtime health shows one worker.
- [ ] Start with `--scale worker=2` and verify runtime health shows two workers.
- [ ] Run two-worker race tests or integration checks for job claiming/leases.
- [ ] Verify scheduler remains one instance.
- [ ] Verify broker execution idempotency tests still pass.
- [ ] Verify provider-heavy jobs are not accidentally multiplied by scheduler scaling.
- [ ] Document operational caution for worker scaling.

## Phase 10 — Validation and soak

- [ ] Run focused runtime supervision tests.
- [ ] Run health route tests.
- [ ] Run repository tests for new process table.
- [ ] Run Postgres migration validation.
- [ ] Run broker/risk/order idempotency regression tests touched by worker scaling concerns.
- [ ] Run frontend typecheck if Docker health UI changes are made.
- [ ] Build Docker image locally.
- [ ] Start Compose stack locally.
- [ ] Confirm `/api/health` is public/minimal.
- [ ] Confirm detailed runtime endpoints require auth.
- [ ] Restart worker container and confirm lifecycle history records the event/inference.
- [ ] Restart scheduler container and confirm lifecycle history records the event/inference.
- [ ] Confirm Postgres data survives app container rebuild/restart.
- [ ] Run backup and restore smoke test.
- [ ] Run at least one paper/demo market-session soak before treating Docker as production-ready.

## Phase 11 — Documentation finalization

- [ ] Update `README.md` with Docker path as optional.
- [ ] Update `docs/getting-started.md` with Docker single-host instructions.
- [ ] Update `docs/operational-scripts-reference.md` with Docker scripts.
- [ ] Update `docs/production-readiness-plan.md` with Docker validation evidence requirements.
- [ ] Keep `docs/specs/production-supervision-spec.md` focused on `start-prod.sh`; link Docker spec as alternate path.
- [ ] Add troubleshooting notes:
  - Postgres healthcheck failing
  - API unhealthy
  - worker crash loop
  - scheduler crash loop
  - backup path permissions
  - `.env.docker` missing/unsafe

## Implementation status

Implemented in this slice:

- Dockerfile and single `docker-compose.yml` for Postgres/API/worker/scheduler.
- Optional `.env.docker` path with `.env.docker.example`.
- Container restart policies.
- Opt-in worker scaling with no `container_name` on worker.
- Postgres persistent volume and backup bind mount.
- Docker helper scripts for up/down/logs/backup/restore smoke.
- Role-neutral runtime process heartbeat table and repository.
- Runtime supervision service with lifecycle events in `observability_events`.
- API, worker, and scheduler runtime heartbeats.
- Public minimal `/api/health`.
- Authenticated `/api/health/runtime` and `/api/health/runtime/events`.
- Tests for runtime supervision, health behavior, Docker file invariants, and route auth.

Validated:

- focused backend tests passed
- frontend typecheck passed
- Docker image build passed
- Compose config validation passed
- Compose smoke stack started on a temporary project and `/api/health` plus authenticated runtime health responded

Pending operational validation:

- backup/restore smoke against an operator-created `.env.docker`
- longer paper/demo market-session soak
- optional multi-worker race/load validation before recommending more than one worker operationally

## Completion criteria

This development is complete when:

- Docker Compose path works without replacing current startup scripts.
- Existing non-Docker production startup remains valid.
- Runtime process heartbeats and lifecycle history are persisted in Postgres.
- Public health is internet-safe.
- Detailed runtime history is authenticated.
- Worker scaling is supported and documented, defaulting to one.
- Scheduler remains single-instance.
- Container restart policies are active.
- Postgres data persists.
- Backup and restore smoke paths are documented and tested.
- Focused tests, Postgres validation, and relevant regressions pass.

## See also

- `specs/docker-deployment-spec.md`
- `specs/production-supervision-spec.md`
- `specs/observability-spec.md`
- `production-readiness-plan.md`
- `operational-scripts-reference.md`
