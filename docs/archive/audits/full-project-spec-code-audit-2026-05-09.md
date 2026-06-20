# Full project spec/code audit

**Status:** reference
**Date:** 2026-05-09  
**Scope:** product specs, implementation coherence, tests, missing features, weak points, and over-engineering risks.

## Executive verdict

The project is substantially more coherent than before, and the code/test suite is in a healthy mechanical state:

- Backend tests: `564 passed, 3 skipped`
- Frontend typecheck: passed
- Worktree at audit time: clean

But the project is not yet effective as a proven autonomous money-making system. It is currently strongest as an operator-facing research, diagnostics, calibration, and paper-execution platform.

| Area | Score | Assessment |
|---|---:|---|
| Spec conceptual coherence | 7/10 | Strong product principles, but docs still mix current/future state. |
| Code/spec coherence | 7/10 | Many specs have direct tests and implementation, but some canonical specs describe stricter targets than code. |
| Test coverage quality | 7.5/10 | Broad local contract coverage; weaker end-to-end/live/provider/broker coverage. |
| Lean architecture | 5/10 | Improved but still heavy: many overlapping reliability/policy/outcome abstractions. |
| Autonomous trading readiness | 3.5/10 | Safer and more observable, but no proven edge and incomplete live reconciliation. |
| Operator/research usefulness | 8/10 | Strong review/debug/calibration surfaces. |

## 1. Spec consistency and coherence

### Product-level coherence is mostly good

The core direction is consistent across:

- `docs/product-thesis.md`
- `docs/features-and-capabilities.md`
- `docs/recommendation-methodology.md`
- `docs/roadmap.md`
- `docs/architecture-simplification-refactor-plan.md`

They agree that the app should be inspectable, reproducible, honest about degraded inputs, and cautious about predictive claims. Broker/effective outcomes are correctly treated as the canonical outcome layer, and calibration/operator trust matter more than raw signal count.

### Remaining spec drift

Several docs still mix current behavior, future target behavior, and completed-refactor language.

Examples:

- `docs/architecture-simplification-refactor-plan.md` says the current refactor scope is complete, but internal phase text still uses language such as “foundation implemented”, “broad migration still planned”, and “persistence split still planned”.
- `docs/roadmap.md` and `docs/features-and-capabilities.md` still describe observability as thin/unstructured, while `docs/observability-spec.md` now documents structured `observability_events`.
- `docs/plan-generation-tuning-spec.md` intentionally combines shipped phase-1 behavior and future autonomous tuning behavior. This is honest, but heavy as a source of truth.
- `docs/recommendation-plan-resolution-spec.md` explicitly says it is stricter than the current evaluator. That makes it a target spec, not a fully implemented current-state spec.

## 2. Code/spec coherence

### Strongly aligned areas

#### Outcome truth

Spec target:

- broker positions override simulated outcomes
- simulation remains fallback evidence

Code support:

- `EffectivePlanOutcomeRepository`
- `TradingPerformanceMetricsService`
- `RecommendationQualitySummaryService`
- dashboard/research/performance paths using effective outcomes

This area is much stronger than before.

#### Broker execution/risk

Spec target:

- pre-submit risk gate
- persisted skipped audit rows
- live Alpaca snapshot support when available
- app ledger remains persisted truth

Code support:

- `OrderExecutionService`
- `BrokerRiskManager`
- `LiveBrokerSnapshot`
- Alpaca account/order/position fetch methods
- order execution and risk tests

Alignment is good for paper-execution guardrails.

#### Data-quality diagnostics

Spec target:

- distinguish missing bars/news from broker untradability

Code support:

- `DataQualityAuditService`
- `GET /api/data-quality/audit`
- frontend data-quality page
- `tests/test_data_quality_audit.py`

Alignment is good.

#### Observability

Spec target:

- run correlation ids
- structured events
- filterable endpoint

Code support:

- `Run.correlation_id`
- `ObservabilityEventRepository`
- `observability_events`
- `GET /api/observability/events`
- job execution emits dispatch/finish/failure events

This is a good first implementation, though not full production observability.

#### News diagnostics

Spec target:

- provider diagnostics
- fallback visibility
- replay/topic provider exclusions visible

Code support:

- `NewsIngestionService`
- topic `query_diagnostics`
- provider status/article/error/attempt data
- news service tests

This is improved but not complete.

## 3. Weak code/spec alignment areas

### 1. Recommendation plan resolution

`docs/recommendation-plan-resolution-spec.md` wants stricter semantics:

- intraday execution truth
- entry within immediate/next-open window
- daily bars only as prefilter
- batch open-plan filtering by default
- expiration must remove stale plans from open set

`RecommendationPlanEvaluationService` has improved but still carries legacy complexity:

- multiple timeframes
- daily + intraday blending
- session/market-region logic
- outcome filtering inside `_list_plans`
- evaluator-internal behavior rather than a small explicit resolution engine

This is probably the most important unresolved correctness gap because outcome truth drives calibration and tuning.

### 2. Autonomous plan-generation tuning

`docs/plan-generation-tuning-spec.md` describes a future automatic evolution system with strict promotion guardrails.

Current app has:

- manual tuning runs
- candidate ranking
- active config promotion
- walk-forward validation
- UI/research surfaces

But it does not yet have a fully autonomous daily promotion loop with all target safety rules. This is documented, but it means the app is not yet an autonomous optimizer.

### 3. Broker reconciliation

The broker risk spec is honest about missing pieces:

- no full persisted Alpaca account reconciliation ledger
- no unrealized P&L from market prices
- no automatic liquidation/cancel on halt
- account activity/fills outside app-submitted orders are not fully reconciled

This is acceptable for controlled paper execution, but not enough for unsupervised trading.

### 4. Topic/macro news

The system now exposes provider limitations better, but broad replay-safe topic coverage is still weak:

- Finnhub free access is company-news oriented
- Google/Yahoo are not always replay/window/topic safe
- topic retry/backoff parity is explicitly incomplete

This weakens macro/industry context quality.

### 5. Context/event extraction

The context layer is more structured, but remains heuristic-heavy. Specs are honest about this. Macro/industry context should be treated as a review aid, not high-confidence alpha.

## 4. Test coherence

### Strengths

The suite covers:

- repositories
- routes
- news provider behavior
- order execution
- broker risk
- effective outcomes
- plan evaluation
- calibration
- policy evaluation
- walk-forward validation
- context quality
- summary service
- ticker deep analysis
- data-quality audit
- frontend type contracts through TypeScript

The full suite passing is meaningful.

### Weak spots

#### SQLite-heavy tests

Most tests run against SQLite. This is fast, but does not fully prove Postgres behavior, migration behavior, lock behavior, or concurrency semantics.

#### Limited live-provider realism

Provider tests use stubs/mocks. This is correct for deterministic tests, but live provider behavior remains risky:

- provider auth limits
- market coverage holes
- replay incompatibility
- inconsistent timestamps
- throttling
- malformed articles

#### Limited full-system trading assertions

The suite verifies contracts, not profitability. It does not prove:

- edge persistence
- stable live win rate
- strategy robustness across regimes
- broker execution quality
- slippage realism
- live-vs-sim outcome consistency

#### Migration-level testing is limited

Alembic heads are clean, but most tests use `Base.metadata.create_all`, not full upgrade/downgrade migration paths. That can miss migration-specific defects.

## 5. Missing or weak features for the stated goal

The ultimate goal is autonomous trading that wins money. The main missing pieces are:

### 1. Proven edge

The app has calibration and outcome tooling, but no strong evidence of profitability yet. It can inspect and improve candidates, but has not demonstrated durable edge.

### 2. Stronger broker reconciliation

Needed before real autonomy:

- persisted account snapshots
- persisted open Alpaca positions independent of app-originated orders
- account activities/fills reconciliation
- realized/unrealized P&L reconciliation
- cancel/liquidate behavior on halt
- reconciliation drift alerts

### 3. Outcome resolution hardening

Plan-resolution semantics must fully align with the canonical spec before calibration can be fully trusted.

### 4. Realistic execution modeling

Current simulated outcomes and paper broker outcomes are useful but imperfect. Missing/weak areas include:

- slippage modeling
- partial fills
- spread/liquidity constraints
- market-hours/auction edge cases
- non-US instrument tradability/routing clarity
- borrow availability for shorts

### 5. Provider reliability and replay safety

Historical context/news replay still has limited broad-topic coverage. This is a major limitation for rigorous backtesting.

## 6. Redundancy and over-engineering

The project has improved, but remains over-layered.

### Biggest redundancy: outcome/reliability/policy stack

Related abstractions include:

- `RecommendationPlanOutcome`
- `EffectivePlanOutcome`
- `BrokerPosition`
- `BrokerOrderExecution`
- `RecommendationDecisionSample`
- `PlanReliabilityFeatures`
- `PlanReliabilityReport`
- `TradePolicyEvaluationService`
- `RecommendationQualitySummaryService`
- calibration summaries
- baseline summaries
- evidence-concentration summaries
- setup-family reviews
- walk-forward validation

Each is defensible, but together they create cognitive load. The risk is that future work adds yet another summary layer instead of simplifying.

### `WatchlistOrchestrationService` is too large

`src/trade_proposer_app/services/watchlist_orchestration.py` is a complexity hotspot. It owns too much:

- cheap scan coordination
- shortlist logic
- deep analysis orchestration
- confidence adjustments
- policy gates
- warnings
- diagnostics
- persistence shaping
- plan construction behavior

It is central and important, but too large to audit easily for trading-logic correctness.

### Settings abstraction is safer but heavier

Current stack:

- `SettingsRepository`
- `SettingsDomainService`
- `SettingsMutationService`
- settings workbench route
- typed frontend contracts

This is safer than raw key/value access everywhere, but a lot of machinery around a key/value table. It is acceptable only if new code consistently uses the typed boundary.

### Backend workbench pattern can spread too far

Workbench endpoints are useful for genuinely complex pages:

- broker workbench
- research workbench
- settings workbench

But if every page gets a custom backend workbench, the API can become page-specific blobs instead of reusable domain contracts.

### Docs are still heavy

There are many markdown docs. The archive helps, but main docs still include current behavior, target behavior, implementation notes, future rules, and caveats. The docs are useful but not lean.

## 7. Highest-priority inconsistencies to fix

### 1. Clean up spec status language

Update the main docs so status labels are consistent:

- `docs/architecture-simplification-refactor-plan.md`
- `docs/roadmap.md`
- `docs/features-and-capabilities.md`
- `docs/observability-spec.md`

Observability should be described as “implemented first structured-event slice; more polish needed” rather than both “implemented” and “thin/unstructured”.

### 2. Reconcile recommendation plan resolution

This is the most important correctness gap.

Target:

- one explicit resolution engine
- daily bars only as prefilter
- intraday truth for ordering
- batch evaluation only open/unresolved by default
- clear handling of expired/no-entry/phantom outcomes

### 3. Strengthen broker reconciliation

Before real autonomy:

- persist account snapshots
- reconcile external broker state
- detect app ledger vs broker mismatch
- halt on reconciliation uncertainty
- optionally cancel open orders on halt

### 4. Reduce orchestration complexity

Split `WatchlistOrchestrationService` around stable boundaries:

- shortlist selection
- deep-analysis orchestration
- plan framing
- diagnostics/persistence shaping

Do not create more abstractions unless they remove real branching.

### 5. Tighten topic/replay provider behavior

The app should continue preferring missing evidence over leakage, but it needs better operator-facing clarity for:

- provider unavailable
- provider unsupported
- replay unsafe
- topic query impossible with current provider stack

### 6. Add migration-level testing

At least one CI/test path should run Alembic migrations against an empty DB and ideally a representative existing DB.

## 8. Overall conclusion

The project is now a credible trading research and operator-control platform. It has strong diagnostics, broad test coverage, explicit specs, and much better outcome/policy/risk boundaries than before.

It is not yet a credible fully autonomous profitable trading bot.

The main blockers are:

1. proof of edge
2. outcome-resolution correctness
3. live broker reconciliation
4. provider/replay data quality
5. reducing trading-logic complexity

The specs are directionally good, but need pruning and sharper current-vs-target separation. The code is mostly coherent with current specs, but some specs intentionally describe future targets that are not fully implemented. The test suite is strong for local contracts, weaker for whole-system/live trading truth.
