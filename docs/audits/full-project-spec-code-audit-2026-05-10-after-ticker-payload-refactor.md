# Full project spec/code audit after ticker-payload refactor — 2026-05-10

**Status:** reference

Audited commit: `b1a58c8` (`Extract ticker analysis payload service`)

## Executive conclusion

The project is coherent as an operator-facing research, diagnostics, paper-execution, and calibration platform. The active docs now mostly say the right thing: the app can generate explainable short-horizon trade plans, persist rich diagnostics, submit to Alpaca paper under guardrails, evaluate outcomes, and support research/tuning workflows.

It is **not yet coherent as a fully autonomous profitable trading bot**. The main blocker is not UI polish or service count. The blockers are evidence and safety:

1. no binding edge-validation/autonomy gate exists yet;
2. broker/app reconciliation drift is visible as a known limitation, not a halt-enforced safety loop;
3. Postgres/Alembic validation is still skipped by default;
4. policy health exists in backend payloads but is not yet a prominent frontend operating control;
5. several tuning/promotion rules are still phase-1 approximations rather than the stricter target behavior described in specs.

The code and tests are strong enough for a research platform, but not strong enough to authorize higher autonomy without additional gates.

## What was checked

- top-level active docs and status labels under `docs/*.md`
- architecture, roadmap, product thesis, methodology, risk, observability, plan tuning, and plan resolution specs
- code boundaries and largest service/module files under `src/trade_proposer_app`
- tests, skips, migrations, and frontend type checking
- obvious spec/code mismatches through targeted source inspection
- active-doc local markdown links

## Validation snapshot

Latest validation from this audit window:

- `.venv/bin/pytest -q` → `579 passed, 3 skipped`
- `cd frontend && npm run check` → passed
- `.venv/bin/python -m alembic heads` → `0040_observability_events (head)`
- active top-level doc status check → no missing/bad statuses
- local markdown link check → no broken local `.md` links found

Skipped tests:

- `tests/test_postgres_integration.py` skips 3 tests unless `POSTGRES_TEST_DATABASE_URL` is configured.

## Spec consistency assessment

### Strong points

1. **The product thesis is honest.** `docs/product-thesis.md` clearly frames the app as an explainable analysis, candidate-ranking, and trade-framing system, not as proven predictive automation.
2. **The roadmap is appropriately conservative.** `docs/roadmap.md` prioritizes reliability, observability, security, and measured recommendation quality before feature expansion.
3. **The architecture doc matches the monolith reality.** `docs/architecture.md` correctly keeps the product as a modular monolith and describes the recently extracted watchlist service slices.
4. **Current behavior docs are now easier to read.** Top-level active docs use normalized status labels: `current behavior`, `current + target behavior`, `active plan`, or `reference`.
5. **Risk, broker execution, effective outcomes, and plan resolution are documented as first-class contracts.** This is important because autonomous trading safety depends on persisted truth, not transient logs.

### Remaining doc/spec coherence issues

#### P1 — Two specs still mix current and target behavior

Files:

- `docs/plan-generation-tuning-spec.md`
- `docs/recommendation-plan-resolution-spec.md`

They are now labeled `current + target behavior`, and both contain explicit current-status sections. That is an improvement, but they remain cognitively risky because they state target rules in imperative language while implementation is only partially aligned.

Most important example: plan-generation tuning says the target system must enforce strict promotion guardrails, diversity/concentration/stability protections, and autonomous daily evolution. The current implementation explicitly ships phase-1 bounded behavior.

Recommendation: keep the current labels for now, but eventually split each into:

- current behavior spec
- target/conformance-gap spec

#### P1 — Missing binding edge-validation/autonomy standard

The docs repeatedly say evidence remains thin and coherent output is not measured edge. That is honest, but there is no binding spec that says when autonomy may expand.

Needed standard should define at least:

- minimum broker-backed resolved sample size
- baseline comparison requirements
- expected value / profit factor thresholds
- max drawdown and loss-streak limits
- out-of-sample and walk-forward stability requirements
- setup-family and regime concentration limits
- demotion/halt rules when live performance degrades

Until this exists, the project cannot safely claim progress toward autonomous money-making beyond paper exploration.

#### P2 — Architecture/methodology docs lag the latest ticker extraction

`docs/recommendation-methodology.md` mentions `TickerTechnicalFeatureService` and `TickerAnalysisPayloadService`, but `docs/architecture.md` still shows only generic `Feature engineering` and does not name `TickerAnalysisPayloadService` or `TickerTechnicalFeatureService` in the pipeline diagram.

This is minor, but active architecture should reflect new source-of-truth boundaries after extraction.

#### P2 — Broker risk spec wording conflicts with implementation around disabled risk management

`docs/broker-risk-management-spec.md` says:

> If risk management is disabled, only the manual halt is bypassed along with all risk limits.

The code in `BrokerRiskManager.assess()` always applies `manual_halt_active` when `risk_halt_enabled` is true, even if `risk_management_enabled` is false. This is likely safer behavior, but the spec sentence is ambiguous/conflicting.

Recommendation: amend the spec to state whether manual halt is absolute or bypassed when risk management is disabled. I recommend making manual halt absolute.

## Code/test coherence with specs

### Strong points

1. **The test suite is broad.** There are 50 test files and 579 passing tests covering routes, repositories, order execution, plan evaluation, tuning, news, context, watchlist orchestration, taxonomy, security helpers, and migrations.
2. **Payload-risk refactors have parity tests.** Watchlist plan framing and ticker analysis payload extraction both have compatibility/parity coverage before extraction.
3. **Broker-backed outcome preference is implemented across multiple surfaces.** Broker order/position lifecycle records feed effective outcomes, performance, calibration, risk, and UI payloads.
4. **Plan resolution has a dedicated engine.** `PlanResolutionEngine` owns the important pure crossing logic, which matches the spec direction.
5. **Provider degradation is visible.** News provider failures, unsupported-market cases, replay-safe provider selection, and fallback diagnostics are tested.

### Main inconsistencies and weak points

#### P0 — Postgres/Alembic confidence is not default-gated

`tests/test_postgres_integration.py` contains important tests, including clean Postgres migration upgrade, but all are skipped unless `POSTGRES_TEST_DATABASE_URL` exists.

This conflicts with the product’s production-like Postgres target. SQLite coverage is useful, but it does not prove migration correctness for the target datastore.

Impact: migration defects, foreign-key behavior differences, JSON/text behavior differences, or transaction assumptions could reach deployment unnoticed.

Recommendation: add a required CI/release smoke path that starts Postgres and runs Alembic upgrade to head plus a minimal repository/API smoke test.

#### P0 — Broker reconciliation is not yet an autonomy-grade safety loop

Current broker risk uses app-owned broker-position records plus optional live Alpaca snapshots during pre-submit checks. This is useful, but not enough for autonomy.

Known gaps:

- live account/order/position snapshots are not persisted as a reconciliation ledger;
- app-vs-broker drift is not classified into severity classes;
- drift does not automatically halt future autonomous submissions;
- unknown broker state can still be treated as warnings/metrics instead of a hard safety state;
- no automatic cancel/liquidate behavior exists when a halt triggers.

The docs acknowledge most of this. The code is coherent with the current v1 spec, but the current v1 spec is not enough for higher autonomy.

#### P1 — `policy_health` is backend-visible but not frontend-prominent

Backend route `src/trade_proposer_app/api/routes/research.py` returns `policy_health`, and tests cover the policy-health contract. But `frontend/src/types.ts` does not include `policy_health` in `PerformanceAssessmentResponse`, and `frontend/src/pages/research-page.tsx` does not render it prominently.

This conflicts with `docs/lean-architecture-and-docs-reconciliation-plan.md`, which says `policy_health` should be the first answer to whether the active selection policy is healthy enough to trust or expand.

Recommendation: add `policy_health` to frontend types and render a top-level Research/Quality card with label, reasons, broker outcome share, sample size, and recommended operator stance.

#### P1 — Plan-generation tuning target guardrails are only partially implemented

The phase-1 implementation is honest and tested, but the target spec is stricter than the code.

Specific gaps:

- promotion eligibility uses simple validation comparisons against baseline;
- target tie tolerances from the spec are not clearly enforced as written (`0.25 percentage points`, `1 win`, `0.02R`);
- broader concentration/diversity/stability protections are not complete;
- autonomous daily evolution is not fully active and should not be treated as live safety policy.

This is acceptable only because the spec explicitly calls current auto flags readiness/configuration flags. It would be unsafe to enable stronger automation before closing these gaps.

#### P1 — Watchlist deletion has weak referential-integrity coverage

`tests/test_watchlist_deletion.py` contains a test named `test_delete_watchlist_in_use_by_job_fails`, but it has no final assertion and contains comments saying SQLite may not enforce the same behavior as Postgres.

This is a concrete test weakness around data integrity. If the intended behavior is “cannot delete watchlist referenced by jobs”, the repository/API should enforce it explicitly or tests should run with FK enforcement equivalent to target behavior.

#### P1 — Partial-persistence semantics remain underspecified

The architecture and roadmap correctly admit limited full rollback. The code persists signals, plans, decision samples, broker audit rows, run artifacts, and outcomes across several steps. This is realistic, but failure semantics are not yet fully specified.

Questions that should become explicit:

- If a proposal run fails after some signals/plans are persisted, what is the canonical run state?
- Which partial artifacts are valid for tuning/calibration?
- Should partial run outputs be excluded from promotion scoring unless marked complete?
- How should replay jobs distinguish partial failures from deliberately skipped names?

This matters because tuning and calibration can be distorted by partial-persistence artifacts.

#### P2 — Observability events are useful but not yet complete

`JobExecutionService` records run dispatch/completion/failure events. `OrderExecutionService.sync_open_executions()` records broker sync start/finish/failure events. This matches the current observability spec at a basic level.

Remaining weaknesses:

- broker sync events are not linked to a run/correlation id when not launched inside a run;
- provider lifecycle events are mostly embedded in run artifacts rather than emitted as structured events;
- order submission/resubmit/cancel/refresh lifecycle has less structured event coverage than broker sync;
- observability write failures are swallowed, which is correct for trading continuity but can hide systematic observability outages unless separately monitored.

#### P2 — Ticker deep analysis still has mixed responsibilities

Recent extractions helped:

- `TickerTechnicalFeatureService`
- `TickerAnalysisPayloadService`

But `TickerDeepAnalysisService` is still 1160 lines and still owns transmission analysis, setup classification, confidence components, relative/reference history loading, price-level suggestion wrappers, fallback handling, and recommendation construction.

This is coherent enough, but it remains a major change-risk area.

#### P2 — Legacy ProposalService remains a large mixed dependency

`ProposalService` is still 1621 lines and contains legacy payload construction, news/context application, feature logic, price history fetching, confidence calculation, and fallback paths. `TickerDeepAnalysisService` still depends on it for important internals.

This is the largest remaining architecture smell. It is tolerable while compatibility paths exist, but it should not become the place for new business logic.

## Effectiveness against stated goals

### Goal: become a full autonomous trading bot

Current status: **not achieved**.

The app can autonomously generate plans and submit to Alpaca paper under configured conditions, but it cannot yet justify autonomous expansion because:

- edge is not proven;
- calibration samples remain thin;
- broker reconciliation is not autonomy-grade;
- no binding edge/autonomy gate exists;
- operator-visible policy health is not yet prominent enough.

### Goal: establish a clear winning edge

Current status: **in progress, not proven**.

The platform has the machinery to measure edge: broker/effective outcomes, calibration, plan reliability, quality summaries, walk-forward validation, decision samples, and tuning runs. But the docs correctly state that evidence remains limited.

The next effectiveness milestone should be evidence quality, not more features.

### Goal: UI lets humans catch mistakes

Current status: **mostly coherent**.

The UI has debugger, run detail, recommendation plans, ticker pages, broker orders, settings, data quality, research, and docs. The main gap is that the most important trust signal, `policy_health`, is not yet presented as a first-class headline.

## Redundancy and over-engineering assessment

### Useful complexity, not currently over-engineered

- Modular monolith structure: appropriate.
- Repository layer: useful because persistence is broad and tests rely on clean seams.
- Workbench endpoints for complex frontend pages: useful because they reduce frontend stitching and metric drift.
- Effective outcome layer: necessary because broker-vs-simulation precedence would otherwise drift.
- Watchlist extraction: useful after parity tests; orchestration is now more understandable.

### Redundant or overgrown areas

#### 1. Proposal/deep-analysis split is still awkward

`ProposalService` is no longer the main run path, but it still owns important helpers used by `TickerDeepAnalysisService`. This creates an old/new hybrid.

Recommendation: continue extracting only clear seams from `ProposalService`, especially price-history fetching, news/context enrichment, and confidence/payload helpers that are still shared.

#### 2. Tuning/reliability metrics have overlapping calculations

The docs say `PlanReliabilityReportService` should become the canonical broker/effective reliability contract. Plan-generation tuning still has its own scoring/promotion calculations. Some duplication is expected, but this is a drift risk.

Recommendation: move tuning eligibility/scoring toward shared reliability bucket or evaluator primitives where possible.

#### 3. Some compatibility wrappers are now migration debt

Compatibility wrappers in watchlist and ticker services protected behavior during extraction. That was correct. They should now be tracked as temporary and removed only when tests/callers migrate.

Recommendation: do not add new private-wrapper patterns unless they are part of a bounded migration with parity coverage.

#### 4. Large tests mirror large services

`tests/test_repositories.py`, `tests/test_routes.py`, and `tests/test_recommendation_plan_evaluations.py` are very large. They provide coverage, but they are hard to navigate and encourage broad fixture coupling.

Recommendation: new tests should be more focused; split only when touching related areas.

#### 5. Taxonomy/news/event extraction are powerful but heavy

`TaxonomyService`, `NewsIngestionService`, and `EventExtractionService` are large and heuristic-heavy. This may be justified by the domain, but it increases the risk of hidden behavior changes.

Recommendation: avoid broad rewrites. Add targeted tests around provider eligibility, event fields, and relationship matching before changing these services.

## Priority recommendations

### P0 — Before increasing autonomy

1. Create `docs/edge-validation-standard.md` with binding autonomy gates.
2. Add broker drift classes and halt rules.
3. Persist broker account/order/position snapshots or an equivalent reconciliation ledger.
4. Add required Postgres/Alembic smoke validation in CI/release flow.

### P1 — Near-term coherence fixes

1. Amend broker risk spec wording around disabled risk management vs manual halt.
2. Add frontend `policy_health` rendering and type support.
3. Fix watchlist deletion referential-integrity behavior/test.
4. Update architecture diagram to include `TickerTechnicalFeatureService` and `TickerAnalysisPayloadService`.
5. Make plan-generation tuning tie tolerance and promotion guardrail gaps explicit in current-status docs/tests.

### P2 — Simplification targets

1. Continue shrinking `TickerDeepAnalysisService` around transmission/setup/confidence seams.
2. Extract `ProposalService` price-history/news-context functionality only when tests pin behavior.
3. Gradually replace watchlist private-wrapper coupling with explicit dependencies.
4. Move tuning/reliability calculations toward shared primitives to reduce metric drift.

## Bottom line

The project is significantly more coherent than before: docs are cleaner, tests are broad, payload-sensitive refactors have parity coverage, and the architecture is converging around explicit persisted contracts.

The honest assessment is that the system is currently a strong **operator-supervised trading research and paper-execution platform**, not yet a safe autonomous trading bot. The next work that matters most is not another feature surface; it is binding edge validation, broker reconciliation halts, Postgres migration confidence, and making policy health impossible for the operator to miss.
