# Full project spec/code/test audit — 2026-05-10 post-watchlist refactor

**Status:** reference
**Auditor:** Aurelio  
**Scope:** active specs/docs, backend services/repositories/routes, frontend surfaces by type-check, test suite, architecture complexity, and autonomy readiness.

## Executive verdict

The project is coherent as an **operator-facing research, diagnostics, paper-execution, and calibration platform**. It is still not coherent as a **fully autonomous profitable trading bot**.

The specs and code strongly support inspectability, degraded-input visibility, paper execution, outcome tracking, and calibration review. They do **not yet** define or enforce a hard enough standard for proving edge, halting on broker/account drift, or safely promoting autonomy.

Recent watchlist refactors improved maintainability materially: `WatchlistOrchestrationService` is now a compatibility/coordinator facade rather than one 2k-line god service. However, the extraction introduced some compatibility-oriented service shapes (`Any`, private-method delegation, orchestration back-references) that should be treated as a transitional state, not a pattern to copy.

## Validation performed

```text
.venv/bin/pytest -q -rs
577 passed, 3 skipped

cd frontend && npm run check
tsc --noEmit passed

.venv/bin/python -m alembic heads
0040_observability_events (head)
```

Skipped tests:

```text
3 skipped in tests/test_postgres_integration.py because POSTGRES_TEST_DATABASE_URL is not configured
```

Repository snapshot:

```text
70 markdown docs under docs/
38 top-level active docs under docs/
7,181 markdown lines across top-level docs
136 backend Python files
50 backend test files
```

Largest backend files now:

| File | Lines | Assessment |
|---|---:|---|
| `services/proposals.py` | 1621 | Older proposal/deep-analysis internals still broad and dense. |
| `services/taxonomy.py` | 1611 | Ontology data, lookup, enrichment, labels, and relationship behavior in one large module. |
| `services/ticker_deep_analysis.py` | 1546 | Data fetching, features, context, diagnostics, and plan support remain tightly coupled. |
| `services/news.py` | 1368 | Provider routing, retry/fallback, diagnostics, replay/live constraints, and normalization are dense. |
| `domain/models.py` | 1144 | Domain model concentration is high but mostly acceptable for a monolith. |
| `services/event_extraction.py` | 1112 | Powerful but heuristic, hard to validate, and high-risk for silent semantic drift. |
| `services/recommendation_plan_evaluations.py` | 991 | Better after resolution engine extraction, but still mixes loading, source selection, persistence, expiration, and outcome shaping. |
| `services/job_execution.py` | 969 | Central dispatcher with broad workflow responsibilities. |
| `services/watchlist_orchestration.py` | 911 | Much improved, but still a compatibility facade with many private wrappers. |

## Scores

| Area | Score | Verdict |
|---|---:|---|
| Product/spec coherence | 8/10 | Strong product thesis and current-state docs; status taxonomy still inconsistently applied. |
| Specs effectiveness for stated goal | 6.5/10 | Excellent for operator trust; insufficient for proving a tradable edge and autonomous safety. |
| Code/spec coherence | 8/10 | Most shipped claims have code/tests; target autonomous behavior remains ahead of implementation. |
| Test/spec coherence | 8/10 | Strong unit/regression suite; weak around Postgres default, broker drift, provider integration, and full workflows. |
| Lean architecture | 6.5/10 | Improved after watchlist extraction; still too many large services and research/read-model layers. |
| Autonomy readiness | 4/10 | Paper automation guardrails exist; unsupervised autonomy remains premature. |
| Operator usefulness | 8.5/10 | Good diagnostics and review surfaces; health/policy/risk signals still too distributed. |

## Stated-goal fit

Project instructions say the app aims to become a full autonomous trading bot, but must first establish a clear winning edge. The UI matters because a human operator should catch mistakes.

Current fit:

- **Strong fit** for research workflow, reviewability, plan framing, diagnostics, and paper-trade audit.
- **Partial fit** for safety through kill switch, pre-submit risk gates, broker order records, and broker position lifecycle records.
- **Weak fit** for autonomous profitability because there is no binding edge-validation gate and broker reconciliation does not yet treat account drift as a first-class halt condition.

The product docs are honest that coherent output is not measured edge. That honesty is a major strength. The next product risk is not presentation; it is whether the system can make a small number of decisions that reliably beat simple baselines after costs and operational frictions.

## Specs consistency and coherence

### What is coherent

1. `docs/product-thesis.md` is realistic and correctly prioritizes reliability, observability, security, measured quality, then expansion.
2. `docs/features-and-capabilities.md` is mostly aligned with shipped behavior and explicitly warns that the app is not yet a proven prediction engine.
3. `docs/roadmap.md` is concise and avoids pretending autonomy is ready.
4. `docs/recommendation-methodology.md` correctly describes signal integrity, staged watchlist generation, cheap-scan/deep-analysis separation, calibration-aware gating, and degraded input handling.
5. `docs/broker-risk-management-spec.md` honestly labels the risk manager as implemented v1 and lists its limits.
6. `docs/observability-spec.md` accurately describes implemented v1 run events and incremental provider/broker coverage.
7. `docs/recommendation-plan-resolution-spec.md` contains a useful conformance matrix and mostly matches the current resolution engine boundaries.

### Remaining documentation inconsistencies

#### D1 — The docs taxonomy is not enforced

`docs/docs-index.md` says every active doc should have exactly one category and active docs should clearly use current/target/active statuses. Several active docs use mixed or non-standard statuses:

- `canonical reference`
- `active`
- `active v1`
- `practical operator guide`
- `authoritative implementation spec`
- missing or non-bold status lines in some specs

Impact: developers still need judgment to know whether a doc is binding current behavior, target behavior, or historical guidance.

Recommendation: normalize active doc statuses to one of:

- `current behavior`
- `target behavior`
- `active plan`
- `reference`
- `archive`

#### D2 — `plan-generation-tuning-spec.md` mixes shipped phase-1 and target autonomy

The spec is honest about the split, but its status is still `authoritative implementation spec` and the opening says it defines required autonomous behavior. This is too easy to misread.

Impact: target auto-promotion behavior may be mistaken for shipped safety.

Recommendation: split into current and target docs, or add section-level status badges throughout.

#### D3 — `recommendation-plan-resolution-spec.md` status understates current/target split

It says `canonical reference`, then says it is intentionally stricter than current code. That is acceptable only if the status makes the conformance role explicit.

Recommendation: change status to `current + target conformance reference`.

#### D4 — architecture/methodology still name `WatchlistOrchestrationService` as the active path

After refactor this is true only as a facade. Execution, scan running, signal building, plan framing, narrative, calibration review, transmission, decision samples, and shortlist selection are now delegated.

Impact: low runtime risk, but the docs no longer explain the real module boundaries.

Recommendation: update `architecture.md` and `recommendation-methodology.md` to describe `WatchlistExecutionService`, `WatchlistScanRunnerService`, `WatchlistPlanFramingService`, and supporting services as the current implementation.

#### D5 — active remediation docs were becoming historical

Remediated after this audit snapshot: completed implementation records were moved to `docs/archive/implementation-plans/`, and `lean-architecture-and-docs-reconciliation-plan.md` was shortened to the remaining active work.

Impact before remediation: active docs were larger and more repetitive than necessary.

Remaining recommendation: keep archiving completed plan detail promptly after each cleanup pass.

## Code/spec coherence

### Strong alignments

1. **Watchlist pipeline is now staged and observable.**  
   Code now separates shortlist selection, scan running, signal building, plan framing, narrative/evidence, calibration review, transmission payloads, decision samples, and execution coordination.

2. **Plan framing payload behavior is protected.**  
   Parity tests freeze actionable long, actionable short, policy-gated short no-action, deep-analysis-unavailable, and cheap-scan-only no-action plan behavior.

3. **Plan resolution has a pure engine.**  
   `PlanResolutionEngine` owns crossing logic, same-bar conservative ties, no-entry diagnostics, phantom outcomes, and buffers without DB/session dependency.

4. **Broker risk v1 is implemented.**  
   `BrokerRiskManager` checks manual halt, open count, open notional, single-position notional, same-ticker duplicates, daily realized loss, consecutive losses, and live snapshot buying power when provided.

5. **Broker execution audit exists.**  
   `OrderExecutionService` persists accepted/failed/skipped broker order records and uses skip rows for risk-blocked submissions.

6. **Observability v1 exists.**  
   Run events and broker order sync events are persisted and queryable.

7. **Post-refactor tests are coherent with specs.**  
   The suite covers shortlist, watchlist policy gates, plan-framing contracts, plan resolution, order execution, tuning, context, data quality, routes, security, worker concurrency, and repositories.

### Important gaps

#### P0 — No binding edge-validation/autonomy gate

The app has calibration, effective outcomes, policy evaluation, quality summaries, baselines, evidence concentration, and walk-forward validation. But there is no single binding standard that says:

- minimum broker-backed resolved sample size
- required profit factor / expectancy / R threshold
- minimum out-of-sample stability
- max drawdown / loss-streak tolerance
- required comparison against baseline policies
- false-discovery controls when many setup/regime slices are explored

Impact: the system can produce many plausible diagnostics without a hard go/no-go rule for autonomy.

#### P0 — Broker drift does not halt autonomy

Broker risk uses app-owned position records plus optional live snapshots, but there is no persisted broker-account/open-order/open-position snapshot ledger and no formal reconciliation severity model.

Missing safety rule: if app ledger and broker state disagree beyond a tolerated explanation, new autonomous submissions must halt.

Impact: acceptable for supervised paper trading; not acceptable for unsupervised live trading.

#### P1 — Immediate/next-open entry semantics are still target behavior

Resolution spec says plans are intended to enter immediately or within five minutes of next market open. The engine currently evaluates entry touches across available post-plan bars inside the horizon.

Impact: simulated outcomes can be more permissive than actual order lifecycle semantics.

#### P1 — Provider lifecycle observability is incomplete

Provider diagnostics exist, but structured events for provider query attempts, exclusions, retry exhaustion, replay/live mismatch, and repeated provider failures are not systematic.

Impact: operator can diagnose many failures, but cross-process correlation remains incomplete.

#### P1 — Postgres/Alembic validation is not in the default path

The only Postgres integration tests are skipped unless `POSTGRES_TEST_DATABASE_URL` is set.

Impact: SQLite can pass while JSON/datetime/index/migration behavior regresses for production-like Postgres.

#### P1 — Credential lifecycle remains weak for production autonomy

Docs and roadmap correctly call this out. The current model has single-user bearer auth and encrypted provider credentials, but not robust rotation/re-encryption/external secret support.

Impact: acceptable for local/single-operator controlled use; weak for hardened deployment.

#### P2 — Health signals are spread across pages

There are health/preflight, data quality, observability events, broker risk, dashboard metrics, policy health, debugger, and run detail surfaces. Each is useful. The operator still has to know where to look.

Impact: diagnosability is good for developers, but high cognitive load for operators.

#### P2 — Context/event extraction remains heuristic

The docs are honest here. The code has richer event fields, but extraction is still heuristic and difficult to validate. This is especially important because context transmission can influence plan promotion.

Impact: context can be useful as explanation and triage, but should not be over-weighted as proof.

## Test/spec coherence

### Strengths

- Broad backend suite: `577 passed`.
- Tests protect the recently risky persisted/operator-facing plan payload behavior.
- Plan resolution engine has pure unit coverage.
- Worker concurrency and scheduler behavior have regression coverage.
- Security, routes, repositories, data quality, context, news, deep analysis, tuning, and broker execution all have tests.

### Weaknesses

1. **Postgres tests are opt-in and skipped by default.**
2. **No default Alembic upgrade smoke test against Postgres.**
3. **Frontend has type-check only, not component or workflow tests.**
4. **Provider integration behavior is mostly unit/fake-level.** That is sensible for determinism, but misses real provider shape drift.
5. **Broker drift/reconciliation tests are shallow relative to autonomy risk.** There are execution/risk tests, but not a full external-state mismatch halt workflow.
6. **Full end-to-end autonomous workflow tests are absent.** There is no test that runs watchlist generation → plan creation → broker submission → sync → position closure → effective outcome → policy health gate.

## Redundancy and over-engineering

### R1 — Quality/research surfaces remain numerous

The project has many related quality concepts:

- recommendation quality summary
- calibration
- baselines
- evidence concentration
- setup-family review
- reliability report
- walk-forward validation
- trade-policy evaluation
- plan-policy evaluator
- signal-gating tuning
- plan-generation tuning

Most are justified individually, but together they are mentally expensive. The project has started centralizing around `policy_health`, but the operator-facing story is not fully collapsed.

Recommendation: keep calculators, but make `policy_health` the primary UI contract for “can we trust/expand this policy?”

### R2 — Watchlist refactor is useful but transitional

The extraction reduced `WatchlistOrchestrationService` dramatically, but several new services depend on orchestration via `Any` and private wrappers:

- `WatchlistExecutionService`
- `WatchlistPlanNarrativeService`
- `WatchlistPlanFramingService`
- related compatibility wrappers

This is acceptable as a behavior-preserving migration, but it is not yet clean dependency design.

Recommendation: do not add more back-reference services unless they delete substantial duplicated behavior. Over time, give extracted services explicit dependencies and direct tests.

### R3 — `ProposalService` and `TickerDeepAnalysisService` still look like old/new boundary overlap

Docs say `ProposalService` is lower-level helper now. Code still has large modules where older proposal internals, feature engineering, enrichment, and diagnostics can leak into newer workflow logic.

Recommendation: extract only clear seams: market-data retrieval/freshness diagnostics, feature vector construction, and summary enrichment.

### R4 — Taxonomy is a large multi-role module

`taxonomy.py` handles ontology data, governed labels, industry/sector lookup, ticker profiles, enrichment, and relationships. The domain deserves centralization, but the module is too broad.

Recommendation: split data loading/cache, label normalization, relationship lookup, and enrichment when a feature touches that area next.

### R5 — Active docs duplicate planning history

The project has become more disciplined, but active docs still include several implementation records. They are useful to Aurelio, but not all should remain in the canonical reading path.

Recommendation: archive completed plan sections and keep only current decisions/gaps in active docs.

## Missing features by priority

### P0 — Required before higher autonomy

1. Create `edge-validation-standard.md` and enforce it in code/UI.
2. Persist broker account/order/position snapshots and implement drift classification.
3. Halt new autonomous submissions on broker reconciliation uncertainty.
4. Make broker-backed effective outcomes the explicit autonomy gate input.

### P1 — Required before production-grade supervised automation

1. Add provider lifecycle structured events.
2. Add Postgres Alembic smoke validation in CI/default optional workflow.
3. Implement first-class entry-window policy if simulated outcomes are used for execution promotion.
4. Add credential rotation/re-encryption workflow.
5. Put `policy_health`, broker risk, data quality, and latest run failures into one prominent operator status surface.

### P2 — Quality and maintainability improvements

1. Continue shrinking `ProposalService`, `TickerDeepAnalysisService`, `NewsIngestionService`, and `TaxonomyService` only around tested seams.
2. Reduce active docs to a smaller canonical set and archive completed remediation detail.
3. Improve replay/topic provider routing and primary-news contradiction diagnostics.
4. Add frontend workflow tests for the highest-risk operator pages.

## Recommended next sequence

1. **Spec first:** add an edge-validation/autonomy gate standard.
2. **Safety next:** extend broker risk/reconciliation with drift classes and halt rules.
3. **Visibility:** surface policy health + broker risk + data quality prominently in the frontend.
4. **Validation:** add default/CI Postgres migration smoke coverage.
5. **Architecture:** only then continue refactoring large services around clear, tested seams.

## Bottom line

The project is substantially healthier than before the remediation/refactor pass. It is coherent, tested, and honest as a human-supervised paper-trading research platform.

The biggest remaining gap is not another model, dashboard, or provider. It is a binding standard for proving edge and a broker reconciliation safety loop strong enough to stop the system when reality diverges from the app ledger.
