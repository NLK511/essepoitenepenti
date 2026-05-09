# P0-P4 remediation plan

**Status:** active implementation record
**Created:** 2026-05-09

This plan turns the latest audit into execution priorities. P0 protects outcome truth first; later phases reduce autonomy and maintenance risk.

## P0 — Outcome-resolution correctness

Goal: calibration and tuning must not learn from misleading simulated outcomes.

Implemented in this pass:
- `PlanResolutionEngine` remains the pure crossing engine.
- `RecommendationPlanEvaluationService._resolve_trade_like_outcome()` now uses intraday data whenever it is available, even when daily bars disagree.
- Daily data without intraday can still prove no-entry/open prefilter states, but terminal daily outcomes without intraday become pending with an explicit intraday-required source.
- Legacy copied evaluator logic was removed from `RecommendationPlanEvaluationService`.
- Regression coverage added for daily/intraday disagreement.

Remaining follow-up:
- make the immediate-or-next-open entry window explicit in the engine if trade submission semantics become stricter.

## P1 — Broker reconciliation and broker observability

Goal: paper/live execution must fail closed when broker state is uncertain.

Implemented in this pass:
- broker open-order sync emits structured observability events:
  - `broker.order_sync_started`
  - `broker.order_sync_finished`
  - `broker.order_sync_failed`
- the service builder wires `ObservabilityEventRepository` into `OrderExecutionService`.

Remaining follow-up before unsupervised live trading:
- persist periodic Alpaca account snapshots
- reconcile external orders/positions/activities beyond app-submitted lifecycle records
- halt on app-ledger vs broker-state drift
- optionally cancel open orders when a halt is triggered

## P2 — Single operator-facing policy-health contract

Goal: operators need one top-level answer for whether the active selection policy is healthy.

Implemented in this pass:
- `TradePolicyEvaluationSummary` now exposes `policy_health`.
- Research workbench payload includes `policy_health` alongside compatibility fields.
- Health combines sample size, win rate, P&L, calibration gap, and broker-vs-simulation evidence mix.

Remaining follow-up:
- render `policy_health` more prominently in the Research UI
- gradually demote direct lower-level policy/reliability fields to drill-down details

## P3 — Architecture simplification

Goal: reduce duplicate trading-logic locations without weakening auditability.

Implemented in this pass:
- removed `_evaluate_plan_legacy()` from `RecommendationPlanEvaluationService`
- removed `_evaluate_shortlist_legacy()` and obsolete shortlist helper copies from `WatchlistOrchestrationService`
- tests now patch the dedicated `ShortlistSelectionService` boundary rather than monkey-patching orchestration internals

Remaining follow-up:
- extract plan framing from `WatchlistOrchestrationService`
- extract run diagnostics shaping from `WatchlistOrchestrationService`
- delete compatibility fields only after UI/API consumer inventory

## P4 — Docs and governance cleanup

Goal: keep specs binding and clear enough to guide autonomous trading work.

Implemented in this pass:
- this remediation plan records current vs remaining behavior by priority.
- recommendation plan resolution spec should be read as closer to current behavior for intraday precedence after this pass.

Remaining follow-up:
- archive or merge transitional `docs/redesign/` material
- shorten large active specs by moving implementation history to archive
- keep one source of truth per business question
