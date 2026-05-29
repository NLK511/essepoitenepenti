# Full project spec/code/test audit — 2026-05-10

**Status:** reference
**Auditor:** Aurelio  
**Scope:** product docs/specs, backend services/repositories/routes, frontend type-check, test suite, architecture complexity, and autonomy readiness.

## Executive verdict

Trade Proposer App is coherent as an **operator-facing research, diagnostics, paper-execution, and calibration platform**. It is not yet coherent as a **fully autonomous profitable trading bot**, because the product still lacks enough broker-backed evidence, robust broker-account reconciliation, and production-grade autonomous safety loops.

The recent remediation pass improved the highest-risk coherence gaps:

- intraday bars now have precedence over daily bars for terminal simulated outcome truth when available
- copied legacy plan/shortlist evaluators were removed
- policy health has a single top-level operator contract
- structured broker-order-sync events exist
- docs now better identify current vs target behavior

The remaining weaknesses are less about one broken feature and more about **evidence maturity, reconciliation depth, service size, and spec discipline**.

## Scores

| Area | Score | Verdict |
|---|---:|---|
| Product/spec coherence | 8/10 | Good current-state taxonomy; remaining target/current mixing in large specs. |
| Specs effectiveness for stated goal | 6.5/10 | Excellent for operator diagnostics; insufficiently hard-nosed for proving trading edge and autonomous-loss containment. |
| Code/spec coherence | 8/10 | Core contracts mostly implemented; important target gaps remain around broker reconciliation and autonomous tuning. |
| Test/spec coherence | 8/10 | Strong regression suite; weak spots remain around Postgres/Alembic-by-default, provider integration, and full autonomous workflows. |
| Lean architecture | 6/10 | Improving after legacy removals, but several very large services still combine orchestration, scoring, IO, diagnostics, and persistence. |
| Autonomous trading readiness | 4/10 | Controlled paper execution is plausible; unsupervised live autonomy is premature. |
| Operator usefulness | 8.5/10 | Strong diagnostics, pages, artifacts, and docs; health signals still need consolidation and prioritization. |

## Validation run

Executed during this audit:

```text
.venv/bin/pytest -q
572 passed, 3 skipped

cd frontend && npm run check
tsc --noEmit passed

python -m alembic heads
0040_observability_events (head)
```

Repository size snapshot:

```text
52 markdown docs under docs/
177 source/test TS/Python files under src/ and tests/
10,198 markdown lines counted across docs top-level/audits/redesign sample set
```

Largest backend services:

| File | Lines | Audit note |
|---|---:|---|
| `src/trade_proposer_app/services/watchlist_orchestration.py` | 2221 | Still too large; core orchestration, plan framing, diagnostics, calibration, persistence payload shaping remain mixed. |
| `src/trade_proposer_app/services/proposals.py` | 1621 | Older proposal/deep-analysis internals still leak into newer plan workflow. |
| `src/trade_proposer_app/services/taxonomy.py` | 1611 | Valuable but too broad: ontology data, lookup, labeling, enrichment, and relationship behavior in one module. |
| `src/trade_proposer_app/services/ticker_deep_analysis.py` | 1546 | Feature calculation, data fetching, narrative/diagnostic shaping, and plan-support behavior are tightly coupled. |
| `src/trade_proposer_app/services/news.py` | 1368 | Provider routing, diagnostics, normalization, replay/live constraints, and persistence concerns are dense. |
| `src/trade_proposer_app/services/event_extraction.py` | 1112 | Heuristic event extraction is powerful but hard to validate and tune. |
| `src/trade_proposer_app/services/recommendation_plan_evaluations.py` | 991 | Improved after engine extraction, but still owns IO, source selection, persistence, expiration, and outcome shaping. |
| `src/trade_proposer_app/services/job_execution.py` | 969 | Run dispatch is central and tested, but still has broad responsibilities. |

## Stated goal fit

### Stated goal

From project instructions: the app aims to become a full autonomous trading bot, but first must establish a clear winning edge. UI matters because a human operator must be able to catch mistakes.

### Current fit

The app fits the **intermediate product goal** well:

- it generates and stores plans
- it records simulated and broker-preferred outcomes
- it exposes calibration, reliability, tuning, and performance surfaces
- it has paper-order execution, risk limits, kill switch, broker-order audit records, and dashboard metrics
- it exposes degraded data and provider failures rather than hiding them

It does **not yet meet the final autonomous-trading goal**:

- effective actionable outcome history remains too thin and weak to prove edge
- prior measured actionable slice was poor (`39` resolved actionable trades, `23.1%` win rate)
- broker reconciliation is app-ledger-first and does not yet fully reconcile external broker orders, account activities, fills, or drift
- plan-generation tuning has target autonomous behavior in specs, but current implementation is phase-1 bounded/manual-guarded
- provider quality and historical replay coverage are still uneven

## Specs consistency and coherence

### What is coherent

1. **Docs taxonomy is now much better.**  
   `docs/docs-index.md` clearly separates current behavior, target behavior, active plans, references, redesign, and archive.

2. **Product thesis is realistic.**  
   `docs/product-thesis.md` correctly says the app should prefer inspectability, reproducibility, and visible uncertainty over cosmetic completeness.

3. **Roadmap is concise and aligned.**  
   `docs/roadmap.md` accurately prioritizes reliability, observability, credential lifecycle, measured recommendation quality, then feature expansion.

4. **Feature doc is honest.**  
   `docs/features-and-capabilities.md` explicitly says the product is not yet a proven prediction engine and warns that coherent output is not measured edge.

5. **Recommendation outcome specs are materially stronger after remediation.**  
   `docs/recommendation-plan-resolution-spec.md` now reflects intraday precedence and distinguishes remaining target behavior.

6. **Broker risk spec is realistic v1.**  
   `docs/broker-risk-management-spec.md` explicitly lists missing live-account ledger/reconciliation features.

### Remaining spec inconsistencies or weaknesses

#### 1. Large specs still mix current behavior and target behavior

`docs/plan-generation-tuning-spec.md` intentionally has two layers: shipped phase-1 and target autonomous tuning. That is honest, but it makes the document harder to use as a binding implementation spec.

Risk: developers can accidentally interpret target autonomous promotion behavior as shipped behavior.

Recommendation:
- split into `plan-generation-tuning-current.md` and `plan-generation-tuning-target.md`, or add clear section-level badges throughout the current spec.

#### 2. Recommendation resolution spec still says it is stricter than current code

`docs/recommendation-plan-resolution-spec.md` is now mostly aligned, but still includes target-only immediate-or-next-open semantics and reconciliation notes. That is acceptable, but the status line says "canonical reference" while parts are target behavior.

Recommendation:
- keep the conformance matrix, but change the opening status to `canonical current + target conformance reference`.

#### 3. Observability spec is implemented v1 but goal is broader than implementation

`docs/observability-spec.md` says the goal is diagnosability across run, worker, provider, and broker failures. Current implementation has run events and broker-order-sync events, but provider lifecycle events remain partial.

Recommendation:
- add a provider-event conformance table similar to the plan-resolution matrix.

#### 4. Broker autonomy specs do not yet define halt-on-drift clearly enough

Broker risk docs mention missing reconciliation, but the target safety rule should be sharper: if app-ledger state and broker state disagree beyond a tolerated explanation, autonomous order submission should halt.

Recommendation:
- add a `broker-reconciliation-target-spec.md` or extend the broker risk spec with drift classes and halt rules.

#### 5. Outcome/profitability proof standard is still under-specified

Docs explain calibration and reliability, but they do not yet define a strict enough standard for declaring a trading edge.

Missing examples:
- minimum broker-backed sample size before live autonomy
- minimum out-of-sample win rate/profit factor/expectancy thresholds
- baseline comparison requirements
- max drawdown or loss-streak bounds
- false-discovery controls when many slices are explored

Recommendation:
- create a small `edge-validation-standard.md` and make it a gate before autonomy claims.

## Code/spec coherence

### Strong alignments

1. **Outcome resolution has a clear core engine.**  
   `PlanResolutionEngine` isolates crossing logic and is directly unit-tested.

2. **Evaluator now honors intraday truth when present.**  
   `RecommendationPlanEvaluationService._resolve_trade_like_outcome()` uses intraday bars if available and only falls back to daily prefilter states when intraday is absent.

3. **Shortlist logic is now extracted.**  
   `ShortlistSelectionService` owns shortlist floors, ranking, lane decisions, and catalyst scoring.

4. **Policy health is centralized.**  
   `TradePolicyEvaluationSummary.policy_health` gives the Research workbench one top-level health contract.

5. **Risk manager matches v1 spec.**  
   `BrokerRiskManager` checks manual halt, open position count, notional limits, same-ticker duplicate limits, realized daily loss, loss streak, and live broker buying power when available.

6. **Structured observability exists.**  
   `ObservabilityEventRepository` and `/api/observability/events` implement the v1 route; `JobExecutionService` and `OrderExecutionService` now emit events.

7. **Docs/current feature list match many shipped UI/API features.**  
   Features doc claims around data-quality audit, ticker drill-down, debugger filtering, broker orders, calibration, and effective outcomes are consistent with implemented services/routes from prior remediation.

### Important code/spec gaps

#### P0 — Broker drift is not a first-class autonomous halt condition

The system uses live broker snapshots in pre-submit risk checks, but it does not yet persist a full broker-account snapshot ledger or compare external broker state against app state as a required safety invariant.

Impact:
- safe enough for supervised paper execution
- not safe enough for unsupervised live execution

Needed:
- persisted account snapshots
- persisted external open orders/positions snapshots
- account activities/fills reconciliation
- drift severity classes
- halt-on-uncertain-broker-state

#### P0 — Edge validation standard is missing

Code can summarize outcomes, calibration, walk-forward validation, and policy health, but there is no single binding gate that says "this strategy is good enough to become more autonomous."

Impact:
- the app can optimize noisy slices
- operator may see many diagnostics without a decisive go/no-go standard

Needed:
- minimum resolved broker/sample thresholds
- baseline comparison rule
- expected value/profit factor threshold
- drawdown/loss-streak threshold
- stability over time windows

#### P1 — Immediate-or-next-open entry semantics are not first-class in the resolution engine

The spec says each plan should be treated as intended to enter immediately or within 5 minutes of next open. The current engine resolves across available bars after computed time/horizon, but this strict execution-window policy is not a first-class engine input.

Impact:
- simulated outcomes may still be more permissive than a real order lifecycle if an entry occurs much later inside the horizon

Needed:
- explicit entry-window policy in `PlanResolutionConfig`
- tests for generated-at-close, generated-during-market, and stale late entry

#### P1 — Provider lifecycle observability remains incomplete

Provider diagnostics exist in news/data-quality payloads, but structured observability events for provider routing, provider exclusion, repeated provider failures, and replay/live mode mismatch are not systematic.

Impact:
- failures can be diagnosed, but not always correlated cleanly across runs/processes

Needed:
- provider query events keyed by run/correlation id
- provider exclusion events for query-type/mode/window incompatibility
- summarized provider failure rate events

#### P1 — Postgres/Alembic validation is not default

There is a Postgres integration test and a manual workflow, but the default validation path is SQLite-heavy.

Impact:
- migrations and JSON/datetime behavior can regress in production-like DBs without default detection

Needed:
- CI/default optional path with `POSTGRES_TEST_DATABASE_URL`
- at least one Alembic upgrade/downgrade smoke test against Postgres

#### P2 — UI health signal consolidation is incomplete

Backend now has `policy_health`, data-quality audit, observability events, health/preflight, broker risk, and dashboard metrics. These are valuable, but still spread across pages.

Impact:
- operator can diagnose issues, but must know where to look

Needed:
- one top-level operator status card with links into health, data quality, broker risk, policy health, and latest run failures

#### P2 — Ticker analysis still depends on older proposal internals

The feature docs explicitly acknowledge this. Code size in `proposals.py` and `ticker_deep_analysis.py` confirms the dependency remains material.

Impact:
- harder to reason about plan-generation semantics
- risk of stale proposal-engine assumptions affecting redesign-native plan flow

Needed:
- extract technical feature engine
- extract plan-framing engine
- keep proposal narrative/summary separate from trade-level construction

## Test/spec coherence

### Strengths

- Full test suite passes: `572 passed, 3 skipped`.
- Tests cover plan resolution engine, recommendation evaluator, shortlist selection, policy behavior, broker risk/order execution, news diagnostics, context quality, data-quality audit, and routes.
- Frontend TypeScript check passes.
- Migration head is singular.
- Regression tests now check daily/intraday disagreement.
- Tests were updated to patch service boundaries instead of orchestration internals.

### Weaknesses

1. **Integration realism is still limited.**  
   Most tests use SQLite and mocks. This is appropriate for speed, but insufficient for confidence in Postgres production behavior.

2. **Provider behavior is hard to test end-to-end.**  
   Tests validate routing/diagnostics logic, but not enough live/replay provider compatibility matrices.

3. **Autonomous tuning target behavior is under-tested.**  
   Phase-1 tuning is tested, but the stricter autonomous promotion guardrails in the spec are not fully executable as tests because the target is not fully implemented.

4. **Broker reconciliation target behavior is not testable yet.**  
   Current tests validate app-submitted order lifecycle and risk checks, but not external broker drift, account activities, and halt-on-drift.

5. **Frontend tests are mostly type-level.**  
   `tsc --noEmit` is useful, but it does not prove UI behavior for complex operator workflows.

## Missing features or incomplete capabilities

### Required before unsupervised live trading

1. Broker-account snapshot persistence.
2. Broker external order/position/activity reconciliation.
3. Halt on broker/app drift or uncertain broker state.
4. Explicit edge-validation gate before autonomy expansion.
5. Runtime policy that blocks autonomy when sample/evidence health is insufficient.
6. Stronger credential lifecycle: rotation, re-encryption, safer production defaults.
7. More systematic provider lifecycle events.
8. Postgres-backed migration/integration tests in default or CI validation.

### Important for recommendation quality

1. More resolved broker-backed outcomes.
2. Baseline strategy comparison as a first-class UI/API contract.
3. Clearer overfit protection for setup-family/regime slices.
4. Better replay/provider coverage for historical topic news.
5. More explicit entry-window simulation to match broker execution semantics.

### Important for operator UX

1. One top-level status/health page or card.
2. Stronger UI prominence for `policy_health`.
3. Clearer separation of simulated outcome, broker outcome, and effective outcome in every review surface.
4. Provider failure timeline linked from run detail.

## Redundancy and over-engineering findings

### 1. Too many overlapping quality abstractions

The app has:

- recommendation quality summary
- calibration summary
- reliability report
- policy evaluation
- policy health
- performance assessment
- trading performance metrics
- walk-forward validation
- evidence concentration

These are not all redundant, but the operator-facing hierarchy is still too complex.

Recommendation:
- make `policy_health` the headline
- make reliability/calibration/performance/walk-forward subordinate drill-down facets
- avoid adding another summary layer

### 2. Settings still have a compatibility-heavy boundary

`SettingsRepository` remains key/value compatibility storage, with typed domain services layered on top. This is acceptable short-term, but each new setting risks adding another layer of indirection.

Recommendation:
- keep typed domain views
- avoid new raw key reads in business logic
- consider schema-backed settings only when churn stabilizes

### 3. Watchlist orchestration remains a god service

Even after removing `_evaluate_shortlist_legacy()`, `WatchlistOrchestrationService` is still 2221 lines.

Still mixed together:
- run orchestration
- plan framing
- persistence payload shaping
- diagnostics
- calibration context
- operator explanation strings
- fallback behavior

Recommendation:
- next extraction should be plan framing, not another reporting adapter

### 4. Taxonomy service is too broad

`TickerTaxonomyService` likely contains multiple concepts:
- static ontology lookup
- label formatting
- relationship graph traversal
- enrichment and fallback logic
- transmission support

Recommendation:
- split only when a real seam is clear: graph/read-through logic and label-formatting are likely first candidates

### 5. Plan-generation tuning spec may be over-specified relative to implementation maturity

The target spec is ambitious and useful, but it is larger than the live implementation. This creates a governance burden.

Recommendation:
- keep the target, but make current conformance tables executable and short

### 6. Historical redesign docs still leak into active understanding

The docs index warns that `docs/redesign/` is transitional, but those docs remain prominent and can confuse current behavior vs target architecture.

Recommendation:
- merge current behavior into canonical docs
- archive historical redesign material more aggressively once references are updated

## Priority recommendations

### P0 — Safety and truth

1. Define and implement broker drift reconciliation with halt-on-uncertain-state.
2. Define edge-validation standard and block autonomy claims until it passes.
3. Add entry-window semantics to `PlanResolutionEngine` if simulated plans are meant to mirror bracket-order execution closely.

### P1 — Evidence and observability

1. Add provider lifecycle structured events.
2. Make Postgres/Alembic upgrade validation a normal CI/default path.
3. Persist broker account/open-order/open-position snapshots.

### P2 — Operator clarity

1. Put `policy_health` prominently in Research/dashboard UI.
2. Add one top-level health/status summary that links to policy, data quality, broker risk, provider failures, and run failures.
3. Make effective-vs-simulated-vs-broker outcome semantics visually explicit everywhere.

### P3 — Architecture simplification

1. Extract plan framing from `WatchlistOrchestrationService`.
2. Extract technical feature calculation from `TickerDeepAnalysisService`/`ProposalService`.
3. Reduce duplicated quality summary layers by making lower-level reports facets of policy health.

### P4 — Docs cleanup

1. Split or badge `plan-generation-tuning-spec.md` sections by current vs target.
2. Add conformance tables to observability and broker reconciliation docs.
3. Archive or merge remaining redesign docs.
4. Add `edge-validation-standard.md` as the autonomy gate.

## Bottom line

The project is in a much healthier state than before the recent remediation. The code, tests, and docs mostly agree on the product as an operator-facing trading research and paper-execution system.

The honest blocker is not UI polish or lack of features. The blocker is that **autonomous profitability is not proven**, and the broker/reconciliation layer is not yet strict enough for unsupervised live trading.

The next work should therefore prioritize:

1. broker-state truth and halt-on-drift
2. edge-validation gates
3. Postgres/provider observability hardening
4. continued service simplification

Do not expand autonomous execution until those gates are in place and the outcome data improves materially.
