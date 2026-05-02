# Architecture Simplification Refactor Plan

## Status
In progress. Phase 1 effective outcomes is implemented. Phase 2 shared performance metrics is implemented. Phase 3 now has the normalized `TradeDecisionPolicy` foundation, live watchlist orchestration is built from the active policy, and generated plans persist policy snapshots. Phase 4, Phase 5, and Phase 6 now have typed foundations. Phase 7 has broker and research workbench read models. An additional audit of remaining abstraction drift has been completed to guide the next cleanup batches. Later consumer migrations must continue incrementally with specs/tests before behavior changes.

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

Canonical contracts:
- `TradingPerformanceMetricsService` for aggregate broker/effective performance summaries
- `PlanReliabilityReportService` for confidence/setup/action reliability cohorts used by Research now and by tuning/gating migrations next

Status: aggregate summaries are implemented and consumed by dashboard/performance assessment. The first reliability report slice is implemented for the Research workbench.

### 3. Policy/tuning overlap
Plan-generation tuning, signal-gating tuning, calibration threshold adjustments, and live watchlist orchestration all affect whether a plan is tradable, but there is no single policy object describing the active trade-selection policy.

Canonical targets:
- `TradeDecisionPolicy` describes the active/selected trade-selection policy
- `PlanPolicyEvaluator` scores a policy against broker-preferred historical outcomes with one shared evaluator
- `TradePolicyEvaluationService` composes policy evaluation with the canonical reliability report for operator-facing quality summaries

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
- `AccountRiskState` for the live account-risk read model

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

### 8. Outcome cohort duplication
Calibration, setup-family review, and some tuning/reporting paths still rebuild the same outcome buckets and sample-status math locally.

Canonical target: `RecommendationOutcomeCohortBuilder` for shared outcome cohort grouping and sample-status math.

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
Status: foundation implemented; first live consumer migrated; first additive policy evaluator implemented.

Implemented:
- `TradeDecisionPolicy`
- `PlanPolicyEvaluator` and active-policy evaluation in recommendation quality summary
- `SignalGatingPolicy`
- `TradeDecisionPolicyService.active_policy()`
- live watchlist orchestration builder passes the active policy instead of separately wiring confidence, signal-gating, and plan-generation settings
- watchlist orchestration honors policy action/setup-family filters when configured
- tests for confidence threshold normalization, action filters, and setup-family filters

Implemented additionally:
- generated recommendation plans persist `trade_policy_id` and `trade_policy_snapshot`

Still needed:
- tuning/search uses `PlanPolicyEvaluator` or narrower shared evaluators when comparing explicit policy/config versions beyond the active policy snapshot

Acceptance criteria:
- every generated plan records the policy version/config used
- broad search can evaluate a policy without reaching into UI/settings internals
- risk manager remains separate from alpha/selection policy

### Phase 4 — Settings domain split
Status: typed domain view foundation implemented; persistence split still planned.

Implemented:
- `SettingsDomainService`
- `StrategySettings`
- `RiskSettings`
- `ExecutionSettings`
- `OperatorSettings`
- tests proving the legacy key/value settings can be read through domain-specific views
- `RiskHaltEvent` audit records
- `/api/risk/halt-events`
- risk halt/resume writes an audit event while keeping current halt state in compatible settings keys

Still needed:
- migration path that keeps existing persisted setting keys compatible if settings are later split into physical tables
- optional actor identity beyond the current `operator` default
- keep remaining typed setting writes behind `SettingsMutationService` so new code does not bypass the typed write façade

Acceptance criteria:
- risk halt/resume history is queryable
- execution settings do not need to parse strategy tuning settings
- settings UI still works without data loss

### Phase 5 — Status taxonomy
Status: foundation implemented; broad migration still planned.

Implemented:
- `domain/statuses.py` with domain-specific status enums/constants
- effective outcome and shared metrics code use canonical outcome/position status constants
- status helper functions for normalization, terminal execution checks, resolved trade outcomes, preflight status checks, and broker-position-to-outcome mapping
- tests for status helper mappings
- health/preflight/dashboard, broker-orders, debugger, and plan-generation-tuning consumers use canonical helpers for their remaining obvious status checks

Still needed:
- migrate remaining raw status-string comparisons where it reduces ambiguity
- keep front-end and backend consumers aligned as new status domains are added

Acceptance criteria:
- no analytics code compares unrelated raw status strings directly
- order execution, position lifecycle, plan status, outcome status, and job status remain distinct

### Phase 6 — Plan responsibility split
Status: execution-candidate foundation implemented; order-execution migration implemented.

Implemented:
- `ExecutionCandidate`
- `ExecutionCandidateResult`
- `ExecutionCandidateBuilder`
- order execution submission path uses `ExecutionCandidateBuilder` for candidate validation and quantity/client-order-id derivation
- tests for valid candidate extraction and invalid-plan skip reason
- `PlanReliabilityFeatures` and `PlanReliabilityFeatureBuilder`
- plan-generation tuning eligible-record selection now uses the shared reliability feature builder

Still needed:
- migrate future broad search/calibration consumers onto `PlanReliabilityFeatureBuilder` where they currently duplicate feature derivation
- recommendation plans remain stable proposed-plan artifacts

Acceptance criteria:
- broker execution can be tested from an execution candidate without loading full orchestration state
- broad search consumes normalized features and effective outcomes

### Phase 7 — Backend read models for complex pages
Status: broker and research read model foundations implemented.

Implemented:
- `/api/broker-workbench` returns broker orders, broker positions, risk state, recent halt audit events, broker sync state, and counts in one backend-reconciled payload
- Broker Orders frontend page consumes `/api/broker-workbench` instead of separately stitching orders, positions, risk, and broker sync status from raw settings
- `/api/research/performance-workbench` returns latest assessment, broker summary, effective outcome summary, calibration summary/report, walk-forward validation, near-entry-miss winners, entry-miss diagnostics, and windows in one backend-reconciled payload
- route tests for broker and research workbench payloads

Implemented additionally:
- Research frontend page consumes the expanded research performance workbench instead of stitching separate calibration-report, walk-forward, and near-entry-miss API calls
- `/api/settings/workbench` returns settings, preflight, and recent broker order audit context
- Settings frontend page consumes `/api/settings/workbench` instead of separately fetching settings, preflight, and broker orders

Still needed:
- remove legacy endpoints only if no longer useful for API consumers; for now they stay as focused lower-level contracts

Acceptance criteria:
- page payloads contain source labels and pre-reconciled metrics
- frontend typecheck and route tests protect page contracts

## Consumer migration plan

The remaining cleanup is a set of safe consumer migrations, not a single destructive removal pass.

Order of work:
1. Inventory consumers with repository-wide searches for raw settings getters, raw status comparisons, lower-level API calls, and duplicate performance/outcome math.
2. Migrate backend services before frontend pages so operator views can rely on reconciled backend contracts.
3. Prefer domain adapters over direct legacy getters:
   - strategy consumers use `SettingsDomainService.strategy_settings()` or `TradeDecisionPolicyService`
   - execution consumers use `SettingsDomainService.execution_settings()`
   - risk consumers use `SettingsDomainService.risk_settings()` and risk halt audit records
   - operator/news consumers use `SettingsDomainService.operator_settings()`
4. Replace analytics and execution status checks with canonical constants/helpers from `domain/statuses.py` when the status belongs to a modeled domain.
5. Keep focused lower-level API endpoints while internal consumers are migrated; remove only code that has no repository consumers and no intended public/debug value.
6. After each batch, run targeted tests, the full backend test suite, and frontend typecheck before commit.

Current migration batches:
- Batch A: settings-domain consumers and broker/risk status constants. Status: implemented for backend service/route consumers that only read domain settings; typed writes are now routed through `SettingsMutationService` for the plan-generation active config and risk/order/evaluation/speech settings paths.
- Batch B: recommendation/outcome analytics status constants. Status: implemented for core outcome repositories, calibration, setup-family review, ticker summary, broker risk, and order execution paths.
- Batch C: remaining frontend duplicate fetches that have a suitable backend workbench contract. Status: implemented for Research, Settings, and Broker Orders. Research now consumes one performance workbench payload for performance assessment, calibration report, walk-forward validation, and near-entry-miss winners. Settings now consumes one settings workbench payload for settings, preflight, and recent broker audit context. Broker Orders now consumes broker sync state included in broker workbench instead of issuing a separate `/api/settings` read.
- Batch D: deprecate/remove only confirmed dead code after a final consumer inventory. Status: completed for this refactor batch. No endpoint was removed: the remaining lower-level APIs are either still used by tests/docs/API consumers, still used for mutations, or intentionally retained as focused API/debug contracts. No frontend page now depends on the older Research multi-fetch pattern, Settings multi-fetch pattern, or Broker Orders settings side-fetch.

## Regression protocol
For each phase:
1. Update or create the spec before behavior changes.
2. Add unit/route tests for the canonical contract.
3. Migrate one consumer at a time.
4. Run targeted tests.
5. Run full backend tests and frontend typecheck before commit.
6. Keep raw legacy adapters available until all consumers are migrated.

## Remaining drift audit
The audit found the following areas still worth reconciling, from highest to lowest urgency:

### High priority
1. **Settings boundary drift**
   - Read paths are still split across `SettingsRepository`, `SettingsDomainService`, and ad hoc route/service access.
   - Mutation paths are better, but legacy route aliases still make the settings surface look larger than it really is.
   - Plan: keep `SettingsRepository` as the persistence/compatibility layer, make `SettingsDomainService` the only typed read façade for new consumers, and keep `SettingsMutationService` as the only typed write façade. The typed read façade should cover strategy, risk, execution, operator, and lightweight scheduler/runtime state.

2. **Policy/reliability contract overlap**
   - `TradePolicyEvaluationService`, `PlanPolicyEvaluator`, and `PlanReliabilityReportService` are separate, but they represent one operator question: "is the active selection policy healthy against broker-preferred outcomes?"
   - Plan: keep the lower-level calculators as facets, but move all operator-facing quality/tuning consumers onto `TradePolicyEvaluationService` so fetch/reconciliation logic stays in one place. The active-policy quality summary now flows through `TradePolicyEvaluationService.summarize_active_policy()` instead of stitching policy selection in the caller.

3. **Broker reconciliation and workbench coordination**
   - Broker orders, positions, risk state, halt events, and broker sync status are still stitched together across a few backend layers.
   - Plan: grow `BrokerReconciliationService` / broker workbench payloads into the canonical read model for operator-facing broker state, while leaving lower-level endpoints available as focused/debug contracts.

4. **Status taxonomy cleanup**
   - Raw status-string checks still exist in a few backend and frontend spots where modeled statuses already exist.
   - Plan: migrate remaining obvious comparisons to `domain/statuses.py` or to component-specific domain helpers when the status is not shared.

### Medium priority
5. **Frontend helper drift**
   - The shared utility module is useful, but it can become a dumping ground if every label/tone formatter gets extracted blindly.
   - Plan: keep only truly identical mappings in shared helpers, and keep domain-specific or single-use label logic local when it communicates meaning better there.
   - The remaining obvious reuse targets are run-status counters and plan-generation tuning config/run tones.

6. **Duplicate page fetch/summary glue**
   - Some pages still make multiple API calls and merge summary data locally when a backend workbench would be clearer.
   - Plan: only add a new backend workbench when the page is stitching together unrelated resources that have a strong read-model shape; otherwise keep the page-local logic.

### Low priority
7. **Calibration/tuning helper redundancy**
   - Outcome bucket math and similar reliability cohort logic should stay centralized, and any new code should reuse `RecommendationOutcomeCohortBuilder` or the canonical reliability services.
   - Plan: treat any new local bucket math as a bug unless there is a concrete domain difference.

## Current reconciliation plan
Continue cleanup in small batches, in this order:
1. Finish migrating remaining read-only settings consumers to `SettingsDomainService` and keep all typed writes behind `SettingsMutationService`.
2. Move recommendation-quality and tuning consumers onto `TradePolicyEvaluationService` so the policy/reliability question has one shared contract.
3. Expand the broker workbench/reconciliation surface only where it removes real stitching logic.
4. Remove remaining raw status-string comparisons where a canonical status helper already exists.
5. Keep frontend shared helpers narrowly scoped: share only identical mappings, not every local formatting choice.
6. Reuse `RecommendationOutcomeCohortBuilder` wherever new calibration-style grouping appears.
7. After each batch, update the relevant spec, add or adjust tests, migrate one consumer at a time, and only then run the regression suite before commit.
