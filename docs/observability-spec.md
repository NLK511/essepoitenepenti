# Observability Spec

## Status
Implemented first production-readiness slice.

## Goal
Make run, worker, provider, and broker failures diagnosable across API, scheduler, worker, and operator UI processes.

## Canonical identifiers
Every persisted run has a `correlation_id` generated at enqueue/create time.

The correlation id is intended for:
- log search across worker/API/scheduler output
- linking run summaries, artifacts, broker submissions, and provider diagnostics
- future structured log/event tables

## Current run fields
`Run` includes:
- `id`
- `job_id`
- `job_type`
- `worker_id`
- `correlation_id`
- `lease_expires_at`
- status/timing/error fields

## Runtime diagnostics
Existing health and debugger surfaces remain responsible for:
- worker heartbeat age
- scheduler heartbeat age
- stale run count
- oldest active lease age
- run status/error/timing/artifact visibility

## Log requirements
Run-dispatch logs must include:
- `run_id`
- `job_id`
- `job_type`
- `worker_id` when available
- `correlation_id`

Provider and broker diagnostics should continue to be stored in run artifacts and domain audit rows. Future work may add a dedicated structured event table, but this first slice avoids a second logging datastore until the run correlation id is deployed.
