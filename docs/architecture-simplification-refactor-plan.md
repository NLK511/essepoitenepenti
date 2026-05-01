# Architecture Simplification Refactor Plan

## Status
In progress. Phase 1 effective outcomes is implemented. Phase 2 shared performance metrics is implemented. Phase 3 now has the normalized `TradeDecisionPolicy` foundation; migrating live generation/search consumers onto that policy remains in progress. Later phases must be implemented incrementally with specs/tests before behavior changes.

## Goal
Make the app leaner and safer for autonomous trading by replacing overlapping, source-specific abstractions with a few explicit product contracts.

The rule is: one business question should have one canonical code path. Raw records may remain, but analytics, tuning, and operator-facing pages should not re-implement reconciliation rules locally.

## Problems to reconcile

### 1. Outcome truth drift
The app historically had simulated `RecommendationOutcome` records before broker execution existed. Broker order audit and broker position lifecycle were added later. This created multiple answers to "what happened to this plan?".

Canonical contract: `EffectivePlanOutcome`.

Status: implemented. Broker positions override simulated outcomes when available. Simulation remains fallback evidence.

### 2. Performance metric duplication
Dashboard, performance assessment, risk views, and research pages have each calculated broker win rate/P&L in local helper functions. This risks metric drift.

Canonical contract: `TradingPerformanceMetricsService`.

Status: implemented in this pass for broker closed-position summaries and effective-outcome summaries. Dashboard and performance assessment use it for broker metrics.

### 3. Policy/tuning overlap
Plan-generation tuning, signal-gating tuning, calibration threshold adjustments, and live watchlist orchestration all affect whether a plan is tradable, but there is no single policy object describing the active trade-selection policy.

Canonical target: `TradeDecisionPolicy`.

This should separate:
- strategy selection policy: what setups are eligible
- risk policy: whether account exposure allows the trade now
- execution policy: how the broker order is submitted

### 4. Settings domain mixing
Settings currently mix operator preferences, strategy policy, risk policy, execution configuration, and runtime halt state.

Canonical target:
- `StrategySettings`
- `RiskSettings`
- `ExecutionSettings`
- `OperatorSettings`
- `RuntimeState` / halt audit records

### 5. Status string ambiguity
Raw strings such as `open`, `failed`, `skipped`, `win`, `loss`, `ok`, and `partial` are used across different domains.

Canonical target:
- `PlanStatus`
- `ExecutionStatus`
- `PositionStatus`
- `OutcomeStatus`
- `JobStatus`

### 6. RecommendationPlan overload
`RecommendationPlan` is currently proposal, operator display object, execution candidate, calibration sample, and performance parent.

Canonical target:
- `RecommendationPlan`: immutable proposed plan
- `ExecutionCandidate`: broker-eligible order candidate derived from a plan
- `EffectivePlanOutcome`: what happened
- `PlanReliabilityFeatures`: normalized feature row for calibration/search

### 7. Page-specific reconciliation in frontend
Complex pages fetch multiple APIs and reconcile locally.

Canonical target: backend page/workbench read models for complex pages, especially broker execution and research performance.

## Phased implementation plan

### Phase 1 — Effective outcome layer
Status: implemented.

Deliverables:
- `EffectivePlanOutcomeRepository`
- `/api/effective-plan-outcomes`
- product analytics use broker-preferred outcomes
- regression tests for broker-overrides-simulation and unresolved broker states

Acceptance criteria:
- broker win overrides simulated loss
- broker loss overrides simulated win
- open broker position remains unresolved
- simulation fallback remains available
- calibration counts broker-resolved outcomes

### Phase 2 — Shared performance metrics
Status: implemented in this pass.

Deliverables:
- `TradingPerformanceMetricsService`
- broker closed-position summary from one shared implementation
- effective-outcome summary from one shared implementation
- dashboard and performance assessment no longer duplicate broker metric math

Acceptance criteria:
- dashboard broker win rate/P&L unchanged
- performance assessment broker win rate/P&L unchanged
- test coverage confirms the shared service counts broker and simulation outcomes correctly

### Phase 3 — Trade decision policy
Status: foundation implemented; consumer migration in progress.

Implemented:
- `TradeDecisionPolicy`
- `SignalGatingPolicy`
- `TradeDecisionPolicyService.active_policy()`
- tests for confidence threshold normalization, action filters, and setup-family filters

Still needed:
- live orchestration reads the normalized policy directly
- tuning/search evaluates explicit policy versions
- generated plans persist policy ID/config snapshot for auditability

Acceptance criteria:
- every generated plan records the policy version/config used
- broad search can evaluate a policy without reaching into UI/settings internals
- risk manager remains separate from alpha/selection policy

### Phase 4 — Settings domain split
Status: planned.

Deliverables:
- typed settings accessors by domain
- migration path that keeps existing persisted setting keys compatible
- kill-switch state separated from durable risk-limit settings, with audit trail

Acceptance criteria:
- risk halt/resume history is queryable
- execution settings do not need to parse strategy tuning settings
- settings UI still works without data loss

### Phase 5 — Status taxonomy
Status: planned.

Deliverables:
- domain-specific status enums/constants
- mapping helpers at API boundaries
- tests for all terminal/nonterminal status mappings

Acceptance criteria:
- no analytics code compares unrelated raw status strings directly
- order execution, position lifecycle, plan status, outcome status, and job status remain distinct

### Phase 6 — Plan responsibility split
Status: planned.

Deliverables:
- `ExecutionCandidate` service/model extracted from order execution submission logic
- `PlanReliabilityFeatures` builder for tuning/search/calibration
- recommendation plans remain stable proposed-plan artifacts

Acceptance criteria:
- broker execution can be tested from an execution candidate without loading full orchestration state
- broad search consumes normalized features and effective outcomes

### Phase 7 — Backend read models for complex pages
Status: planned.

Deliverables:
- broker workbench read model
- research performance workbench read model
- frontend pages stop duplicating backend reconciliation rules

Acceptance criteria:
- page payloads contain source labels and pre-reconciled metrics
- frontend typecheck and route tests protect page contracts

## Regression protocol
For each phase:
1. Update or create the spec before behavior changes.
2. Add unit/route tests for the canonical contract.
3. Migrate one consumer at a time.
4. Run targeted tests.
5. Run full backend tests and frontend typecheck before commit.
6. Keep raw legacy adapters available until all consumers are migrated.

## Current priority after Phase 2
Implement Phase 3, because broad plan-generation search needs an explicit policy object. Without it, search risks optimizing accidental settings spread across orchestration, calibration, tuning, and settings code.
