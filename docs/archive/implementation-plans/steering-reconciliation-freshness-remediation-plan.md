# Steering reconciliation freshness remediation plan

**Status:** completed and archived remediation plan

## Problem

Steering now refreshes broker order/position metadata before decision evaluation, but many decisions can still be marked `broker_reconciliation_stale` because the steering freshness gate only consults `broker_reconciliation_snapshots`.

That is too indirect after a successful broker refresh. A snapshot is useful drift/audit evidence, but it should not be the only freshness source for a mutation-adjacent steering decision.

The observed failure mode:

1. steering preflight refresh succeeds
2. broker order and broker position rows have fresh `updated_at` values
3. some per-ticker reconciliation snapshot rows are older than the steering threshold
4. steering marks those candidates stale anyway

This is safe but noisy and blocks useful steering review.

## Design principle

Use the simplest authoritative source for each question:

- **freshness**: active broker order/position row timestamps and protective-order verification timestamps
- **drift/audit warnings**: reconciliation snapshots
- **operator history**: reconciliation snapshots and observability events

Snapshots should block steering when they report warnings/drift. They should not be the only proof that broker data was refreshed.

## Required behavior

For each steering candidate, reconciliation health should be computed from both:

1. candidate-local broker record freshness
   - pending order: `BrokerOrderExecution.updated_at`
   - open position: `BrokerPosition.updated_at`
   - protected position amendments/close decisions: `BrokerPosition.protective_orders_verified_at` when protective order evidence exists
2. latest reconciliation snapshot for the ticker, if present

Rules:

- If the candidate's active broker record was updated within `steering.max_reconciliation_age_minutes`, freshness may be considered healthy even when the ticker snapshot is older.
- If a latest snapshot exists and has warnings or non-`ok` drift severity, reconciliation is unhealthy regardless of row freshness.
- If no candidate-local broker record timestamp is available, fall back to the snapshot as today.
- For open positions with expected protective orders, stale/missing `protective_orders_verified_at` should make reconciliation unhealthy for live mutation.
- Diagnostics should continue exposing `broker_reconciliation_age_minutes`, now representing the freshest candidate-local broker evidence when available.

## Scope

In scope:

- update `BrokerSteeringStateBuilder` reconciliation health logic
- pass candidate order/position into the health calculation
- add tests covering fresh rows with stale snapshots, stale protective verification, and snapshot warning override
- update broker steering spec

Out of scope:

- deleting reconciliation snapshots
- changing broker sync adapter behavior
- enabling live steering
- rewriting the broker reconciliation audit model

## Task breakdown

### Phase 1 — Specs and tests

- [x] Create this remediation plan.
- [x] Update `docs/specs/broker-position-steering-spec.md` to distinguish freshness from drift snapshots.
- [x] Add tests proving fresh candidate rows prevent false `broker_reconciliation_stale` when snapshots are old/absent.
- [x] Add tests proving snapshot warnings still block steering.
- [x] Add tests proving stale protective-order verification blocks open-position amendment/close candidates.

### Phase 2 — Implementation

- [x] Extend `_broker_reconciliation_health(...)` to accept `order` and `position`.
- [x] Compute candidate-local freshness from `updated_at` and `protective_orders_verified_at`.
- [x] Treat snapshot warnings/non-ok drift as a hard unhealthy override.
- [x] Preserve snapshot fallback when no candidate-local timestamps exist.
- [x] Keep diagnostics/backward-compatible tuple return shape unless a richer object is necessary.

### Phase 3 — Validation

- [x] Run steering workflow tests.
- [x] Run broker/order/reconciliation tests.
- [x] Run route/repository tests if payload behavior changes.
- [x] Manually run steering and verify `broker_reconciliation_stale` drops when broker rows are fresh and snapshots are not warning.

## Acceptance criteria

- Successful steering preflight refresh makes candidate-local broker data fresh for steering.
- Old snapshots do not create false stale decisions when candidate rows were just refreshed.
- Snapshot warnings/drift still block live mutation.
- Stale protective-order verification still blocks position mutations.
- Steering remains dry-run unless explicitly enabled elsewhere.
