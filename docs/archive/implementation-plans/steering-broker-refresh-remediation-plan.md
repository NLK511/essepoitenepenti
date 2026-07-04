# Steering broker-refresh remediation plan

**Status:** completed and archived remediation plan

## Problem

Broker position steering currently runs every 30 minutes as a dry-run decision loop, but it can evaluate before broker order/position metadata has been refreshed. This produces stale reconciliation decisions such as `broker_reconciliation_stale` even when broker data is refreshed shortly after the steering run.

That is safe because steering fails closed, but it is bad operational design:

- steering depends on fresh broker order, position, and protective-leg state
- stale inputs make dry-run decisions noisy
- live mutation should never depend on a separate periodic broker-sync timing coincidence
- a dedicated scheduled broker refresh duplicates what steering itself must guarantee

## Desired design

Steering must own its reconciliation preflight.

Every steering run should:

1. refresh broker order/position metadata first
2. record the refresh result in the steering run summary
3. evaluate steering decisions only after refresh completes
4. fail closed when refresh fails or broker state remains stale
5. keep manual/on-demand broker refresh available from the broker orders page for operator real-time inspection
6. remove the separate scheduled broker refresh path so scheduled refresh work is not duplicated outside steering

## Scope

In scope:

- `BrokerSteeringService.run_once()` or the job execution wrapper must call broker reconciliation before state building
- persist/update existing broker sync runtime settings from that refresh
- expose refresh status in steering run summaries and diagnostics
- remove scheduler-driven automatic broker-order sync
- keep `POST /api/broker-orders/sync` and per-order refresh endpoints for manual UI use
- update tests and docs/specs

Out of scope:

- changing broker adapter semantics
- enabling live steering mutations
- changing broker order submit/cancel/refresh manual controls
- changing the steering decision rules themselves except for refresh preflight handling

## Required behavior

### Steering preflight refresh

Before candidate discovery or decision evaluation, a steering run must call the same reconciliation path used by manual broker sync.

The run summary should include:

- `broker_refresh_attempted: true`
- `broker_refresh_status`: `succeeded`, `failed`, or `skipped`
- `broker_refresh_synced_count`
- `broker_refresh_failed_count`
- `broker_refresh_error` when applicable
- `broker_refresh_completed_at`

If refresh fails:

- dry-run mode may still persist manual-review decisions if state can be loaded, but the run summary must show refresh failure
- live mutation mode must not execute broker mutations
- decisions that depend on fresh broker state must remain blocked/manual-review

If refresh succeeds but the reconciled state is still older than `steering.max_reconciliation_age_minutes`, steering must fail closed as today.

### Remove scheduled broker sync

The scheduler should no longer run `_sync_broker_orders_if_due()` as an automatic periodic task.

The app should retain:

- manual broker page refresh: `POST /api/broker-orders/sync`
- single order refresh: `POST /api/broker-orders/{execution_id}/refresh`
- dashboard/manual refresh buttons if they intentionally call the sync endpoint

Broker sync state (`broker_order_sync_last_at`, count, error) remains useful because steering preflight and manual refresh both update it.

### Job schedule

Keep the broker steering scheduled job:

- `Auto: Broker Steering Dry Run`
- `*/30 * * * *`

Do not add a separate broker-sync job.

## Task breakdown

### Phase 1 — Spec and tests first

- [x] Create this remediation plan.
- [x] Update `docs/specs/broker-position-steering-spec.md` to state steering owns broker reconciliation preflight.
- [x] Update `docs/specs/alpaca-paper-order-execution-spec.md` to clarify broker sync is manual/on-demand plus steering preflight, not separate scheduler-owned periodic sync.
- [x] Add/adjust tests proving steering calls reconciliation before decision evaluation.
- [x] Add/adjust tests proving refresh failure blocks live execution and is reported in run summary.
- [x] Add/adjust scheduler tests proving automatic periodic broker sync is removed while other scheduled work remains.

### Phase 2 — Steering preflight implementation

- [x] Add a small steering preflight method that calls `BrokerReconciliationService.sync_open_orders()`.
- [x] Thread refresh outcome into `BrokerSteeringRunSummary` or the returned summary payload.
- [x] Persist/update broker sync runtime settings from the steering preflight refresh.
- [x] Ensure exceptions are caught, recorded, and fail closed.
- [x] Ensure live mutation is blocked when refresh failed, even if `steering_dry_run=false`.

### Phase 3 — Remove scheduled broker sync

- [x] Stop calling `_sync_broker_orders_if_due()` from the scheduler loop.
- [x] Remove or deprecate interval constants if no longer used by production code.
- [x] Keep the sync helper only if tests/manual tooling still use it, otherwise remove it.
- [x] Update default job/docs references so there is no implied scheduled broker refresh job.

### Phase 4 — UI/API preservation

- [x] Confirm Broker Orders page refresh button still calls `POST /api/broker-orders/sync`.
- [x] Confirm Dashboard broker refresh button, if present, remains manual/on-demand.
- [x] Ensure broker sync state still displays last manual or steering-preflight refresh.

### Phase 5 — Validation

- [x] Run steering workflow tests.
- [x] Run scheduler tests.
- [x] Run route tests covering broker refresh endpoints.
- [x] Run repository/settings tests if sync state persistence changes.
- [x] Confirmed by implementation and regression coverage that steering run summaries expose broker refresh fields. Manual production-run inspection remains an operational check, not an implementation blocker.

## Acceptance criteria

- Every scheduled/manual steering run attempts broker reconciliation before evaluating candidates.
- Steering run summaries show broker refresh status.
- Live mutation is impossible after failed/stale broker refresh.
- No automatic broker refresh runs independently from steering.
- Manual broker refresh from the Broker Orders page still works.
- Dry-run decisions become less noisy because refresh happens before decision evaluation.

## Safety note

This remediation does not enable live steering. It only makes dry-run/live decision evaluation use fresher broker state and removes a misleading separate scheduled sync path.
