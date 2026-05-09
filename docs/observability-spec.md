# Observability Spec

## Status
Implemented.

## Goal
Make run, worker, provider, and broker failures diagnosable across API, scheduler, worker, and operator UI processes.

## Canonical identifiers
Every persisted run has a `correlation_id` generated at enqueue/create time.

The correlation id is used for:
- log search across worker/API/scheduler output
- linking run summaries, artifacts, broker submissions, and provider diagnostics
- querying structured observability events

## Current run fields
`Run` includes:
- `id`
- `job_id`
- `job_type`
- `worker_id`
- `correlation_id`
- `lease_expires_at`
- status/timing/error fields

## Structured events
Structured events are stored in `observability_events`.

Each event includes:
- `run_id`
- `job_id`
- `correlation_id`
- `event_type`
- `severity`
- `source`
- `message`
- `payload_json`
- `created_at`

The job execution path records at least:
- `run.dispatch_started`
- `run.finished`
- `run.failed`

Observability writes must never block or fail trading work. If event recording fails, the app logs a warning and continues.

## API
`GET /api/observability/events` returns recent events and supports filters:
- `run_id`
- `correlation_id`
- `severity`
- `limit`

## Runtime diagnostics
Existing health and debugger surfaces remain responsible for:
- worker heartbeat age
- scheduler heartbeat age
- stale run count
- oldest active lease age
- run status/error/timing/artifact visibility

Structured events complement those read models; they do not replace domain audit rows such as broker order executions, broker positions, risk halt events, or provider diagnostics embedded in run artifacts.

## Log requirements
Run-dispatch logs must include:
- `run_id`
- `job_id`
- `job_type`
- `worker_id` when available
- `correlation_id`
