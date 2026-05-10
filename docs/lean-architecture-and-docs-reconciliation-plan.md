# Lean architecture and docs reconciliation plan

**Status:** proposed remediation plan  
**Created:** 2026-05-09  
**Purpose:** reduce over-engineering, shrink doc complexity, and reconcile current-vs-target specs without weakening trading safety, auditability, or calibration truth.

## Goal

Make the app easier to reason about and safer to evolve by reducing duplicate abstractions and turning the docs into a smaller, clearer source-of-truth set.

This plan does **not** aim to remove useful audit/debug contracts. It aims to remove ambiguity, duplicated interpretation logic, and stale future-state language from the active reading path.

## Non-goals

- Do not remove broker/effective outcome audit history.
- Do not hide degraded input diagnostics.
- Do not collapse domain boundaries that protect trading safety.
- Do not remove focused lower-level API endpoints unless no test, UI, script, or operator-debug workflow still needs them.
- Do not rewrite the app into microservices.

## Guiding rules

1. **One business question, one canonical read path.**
2. **Raw records may remain; reconciliation logic should not be duplicated.**
3. **Docs should separate current behavior, target behavior, and historical context.**
4. **Prefer deleting adapter code over adding another facade.**
5. **Every simplification batch must preserve tests before and after.**
6. **Trading correctness beats architectural purity.**

---

# Part A — Architecture simplification

## A1. Freeze new abstraction creation

### Problem
The project already has many layers around outcomes, quality, policy, calibration, and page read models. New work risks adding more summary/facade classes instead of simplifying existing paths.

### Policy
For the next remediation cycle, new abstractions require one of these justifications:

- removes at least two existing duplicated code paths
- makes a trading-safety invariant testable in isolation
- turns a stale/future spec into current behavior
- reduces a large service’s branching without changing behavior

### Acceptance criteria
- New services/classes added during cleanup include a short docstring saying what duplication or safety concern they remove.
- No new “summary of summaries” service is added unless it replaces an existing one.

## A2. Create an abstraction inventory

### Deliverable
Create `docs/audits/abstraction-inventory-2026-05.md` with a table:

| Contract/service | Business question | Current consumers | Keep / merge / archive | Reason |
|---|---|---|---|---|

### Must inventory

Outcome/performance stack:
- `RecommendationPlanOutcome`
- `EffectivePlanOutcome`
- `BrokerOrderExecution`
- `BrokerPosition`
- `TradingPerformanceMetricsService`

Quality/reliability stack:
- `RecommendationQualitySummaryService`
- `RecommendationPlanCalibrationService`
- `RecommendationPlanBaselineService`
- `RecommendationEvidenceConcentrationService`
- `RecommendationSetupFamilyReviewService`
- `PlanReliabilityReportService`
- `TradePolicyEvaluationService`
- `PlanPolicyEvaluator`
- `PlanReliabilityFeatureBuilder`

Execution/policy stack:
- `RecommendationPlan`
- `ExecutionCandidateBuilder`
- `TradeDecisionPolicyService`
- `OrderExecutionService`
- `BrokerRiskManager`

Settings/read-model stack:
- `SettingsRepository`
- `SettingsDomainService`
- `SettingsMutationService`
- workbench routes

### Acceptance criteria
- Every listed contract has an explicit keep/merge/archive decision.
- Any “keep” decision names the unique business question it answers.

## A3. Collapse operator-facing quality into one contract

### Problem
Quality views currently involve calibration, baselines, evidence concentration, setup-family review, reliability report, active-policy evaluation, and walk-forward validation. These are individually useful but mentally expensive.

### Target
Keep lower-level calculators, but make `TradePolicyEvaluationService` the single operator-facing contract for the question:

> Is the active selection policy healthy enough to trust or expand?

### Implementation approach
1. Add a `PolicyHealthReport` domain/read model if it can replace scattered dictionaries rather than add another parallel summary.
2. Move existing recommendation-quality/research payload assembly toward this single report.
3. Keep calculators private/facet-like from the operator perspective.
4. Mark old direct route/page fields as compatibility fields if they must remain.

### Acceptance criteria
- Research and recommendation-quality pages can explain policy health from one top-level payload section.
- Tests assert that active policy, reliability cohorts, calibration, and walk-forward status are internally consistent in that payload.
- No frontend page recomputes policy/reliability status locally.

## A4. Split `WatchlistOrchestrationService` by behavior, not by technology

### Problem
`WatchlistOrchestrationService` is too large and owns cheap scan, shortlist, deep analysis, policy gating, plan framing, diagnostics, and persistence shaping.

### Target slices
Extract only if behavior can be tested independently:

1. `ShortlistSelectionService`
   - inputs: cheap-scan signals, policy, tuning config
   - output: selected/rejected candidates with reasons

2. `PlanFramingService`
   - inputs: deep-analysis result, policy/config, calibration context
   - output: proposed `RecommendationPlan` or no-action/watchlist plan payload

3. `RunDiagnosticsBuilder`
   - inputs: scan/deep-analysis/persistence outcomes
   - output: summary/artifact diagnostics

Keep orchestration as the coordinator.

### Acceptance criteria
- `WatchlistOrchestrationService` line count and branch count meaningfully drop.
- Existing orchestration tests still pass.
- New tests cover shortlist and plan-framing decisions without constructing a full orchestration run.

## A5. Make recommendation plan resolution a dedicated engine

### Problem
Outcome resolution is both critically important and still partially misaligned with the spec.

### Target
Create a small explicit resolution engine that owns:
- entry touch
- stop/take ordering
- no-entry/expired
- phantom outcomes
- near-entry diagnostics
- daily-prefilter vs intraday-truth separation

`RecommendationPlanEvaluationService` should orchestrate loading/saving, not own crossing semantics.

### Acceptance criteria
- The resolution engine is unit tested without DB/session dependencies.
- Daily bars are only used as prefilter where the spec says so.
- Batch evaluation defaults to unresolved/open plans.
- Existing plan evaluation tests pass or are updated only when the spec is clarified.

## A6. Keep settings boundary but stop expanding it

### Problem
Settings are safer than before but have many layers around a key/value table.

### Target
- Keep `SettingsRepository` as persistence compatibility.
- Keep `SettingsDomainService` as typed read facade.
- Keep `SettingsMutationService` as typed write facade.
- Do not add more settings services unless physical persistence changes.

### Acceptance criteria
- New code does not call raw `get_setting_map()` unless it is in repository/domain/mutation/builders compatibility code.
- Route/service tests cover typed settings views.

## A7. Limit workbench endpoint growth

### Problem
Workbench routes reduce frontend stitching, but can become page-specific blobs.

### Policy
Add or keep a workbench only when a page genuinely reconciles multiple domain resources.

### Keep as workbenches
- broker workbench
- research/performance workbench
- settings workbench

### Avoid new workbenches for
- simple lists
- single-domain detail pages
- formatting-only transformations

### Acceptance criteria
- Every workbench docstring/route comment states which reconciliation it centralizes.
- No frontend page merges unrelated domain state if a workbench already exists.

---

# Part B — Docs reconciliation and size reduction

## B1. Define a canonical docs taxonomy

### Current problem
Main docs mix current behavior, target behavior, historical notes, and implementation plans.

### Target structure

#### Current-state docs
Only describe implemented behavior.

Keep active:
- `product-thesis.md`
- `features-and-capabilities.md`
- `architecture.md`
- `recommendation-methodology.md`
- `operator-page-field-guide.md`
- `raw-details-reference.md`
- `er-model.md`
- `getting-started.md`
- `docs-index.md`

#### Specs
Must state whether they are current behavior or target behavior at the top.

Keep active but normalize:
- `recommendation-plan-resolution-spec.md`
- `broker-risk-management-spec.md`
- `alpaca-paper-order-execution-spec.md`
- `news-provider-reliability-spec.md`
- `news-provider-eligibility-spec.md`
- `data-quality-audit-spec.md`
- `observability-spec.md`
- `plan-policy-evaluator-spec.md`
- `plan-reliability-report-spec.md`
- `plan-generation-tuning-spec.md`
- `signal-gating-benchmark-spec.md`

#### Active plans
There should be very few.

Keep active:
- `roadmap.md`
- this plan until completed
- `recommendation-quality-improvement-plan.md` only if still actively maintained

#### Archive
Move stale or duplicate implementation plans to `docs/archive/`.

### Acceptance criteria
- `docs/docs-index.md` has exactly these categories.
- Every active doc has one of these statuses:
  - `current behavior`
  - `target behavior`
  - `active plan`
  - `reference`
  - `archive`

## B2. Split current-vs-target specs

### Problem
Some specs are hard to use because they mix shipped behavior and future target behavior.

### High-priority split/normalization

#### `plan-generation-tuning-spec.md`
Keep current shipped behavior in the main spec. Move fuller autonomous promotion rules into:
- `docs/target-autonomous-plan-generation-tuning.md`, or
- a clearly marked “Target behavior” appendix.

#### `recommendation-plan-resolution-spec.md`
Keep target semantics, but add a compact “Implementation conformance matrix”:

| Rule | Current status | Code owner | Test owner | Gap |
|---|---|---|---|---|

#### `architecture-simplification-refactor-plan.md`
Convert from active plan to final completion record or archive it after extracting remaining active items into this plan.

### Acceptance criteria
- No canonical current-state doc says “not yet implemented” except in a dedicated “Current limits” section.
- Target behavior is clearly labeled and not confused with shipped behavior.

## B3. Reduce roadmap duplication

### Problem
Roadmap repeats shipped features and overlaps with current-state docs.

### Target
`roadmap.md` should contain only:
- active priorities
- why they matter
- next measurable milestone
- explicitly later items

### Acceptance criteria
- Shipped implementation detail is removed from roadmap and linked to current-state docs.
- Observability wording reflects structured events already shipped while still noting remaining gaps.

## B4. Prune overlapping redesign docs

### Status
Implemented in the 2026-05-10 P3/P4 cleanup pass.

### Result
`docs/redesign/` no longer acts as a second active architecture tree. Stable content was merged into canonical docs and the source redesign files were moved to `docs/archive/redesign/merged-2026-05-10/` for provenance.

Merged destinations:
- principles → `product-thesis.md`
- four-layer architecture → `architecture.md`
- transmission modeling, setup families, and calibration governance → `recommendation-methodology.md`
- UI/navigation principles → `operator-page-field-guide.md`
- persistence direction → `er-model.md`

### Acceptance criteria
- `docs/redesign/README.md` no longer acts as a second active architecture index.
- Operators/developers can understand the active system without reading redesign history.

## B5. Create a docs lint checklist

### Add to `docs/docs-index.md`
A short checklist for doc changes:

- Is this current behavior, target behavior, active plan, reference, or archive?
- Does this duplicate another doc?
- If shipped, is it removed from roadmap future language?
- If target-only, is it clearly marked as not implemented?
- Is there a test/spec/code owner for the behavior?

### Acceptance criteria
- New docs follow the taxonomy.
- Archive docs are not linked as required reading for current behavior.

---

# Part C — Concrete remediation sequence

## Phase 1 — Docs truth cleanup

### Tasks
1. Update `docs/docs-index.md` taxonomy.
2. Normalize status labels across active docs.
3. Update roadmap observability and shipped-feature wording.
4. Convert `architecture-simplification-refactor-plan.md` into completion record or archive.
5. Add conformance matrix to `recommendation-plan-resolution-spec.md`.

### Tests/checks
- Markdown link sanity via `rg`/manual link check.
- No code behavior changes required.

### Done when
- Main docs no longer contradict each other on whether observability/refactor work is implemented.
- Current vs target behavior is obvious.

## Phase 2 — Abstraction inventory and deletion candidates

### Tasks
1. Write `docs/audits/abstraction-inventory-2026-05.md`.
2. Identify duplicate or compatibility-only services/routes.
3. Mark each as keep/merge/archive.
4. Remove only confirmed dead code after `rg` consumer checks and tests.

### Tests/checks
- Full backend tests.
- Frontend typecheck.

### Done when
- Every major abstraction has a named business question.
- Deletion candidates are explicit and safe.

## Phase 3 — Outcome-resolution engine

### Tasks
1. Extract pure crossing/expiration/phantom logic from `RecommendationPlanEvaluationService`.
2. Add focused unit tests matching `recommendation-plan-resolution-spec.md`.
3. Keep service responsible for loading/saving only.
4. Reconcile batch open-plan filtering.

### Tests/checks
- `tests/test_recommendation_plan_evaluations.py`
- `tests/test_repositories.py` relevant evaluation tests
- full backend suite

### Done when
- Plan-resolution spec no longer says the live evaluator is partially aligned for core semantics.

## Phase 4 — Orchestration slimming

### Tasks
1. [x] Extract shortlist selection if tests can isolate behavior.
2. [x] Extract plan framing if tests can isolate behavior.
3. [x] Extract decision-sample persistence from orchestration.
4. [x] Extract ticker-signal snapshot construction from orchestration.
5. [x] Extract calibration-review payload generation from orchestration.
6. [x] Extract transmission/signal-breakdown payload generation from orchestration.
7. [x] Extract plan narrative/evidence/risk text generation from orchestration.
8. [x] Extract full watchlist run coordination from orchestration.
9. [x] Extract cheap-scan/deep-analysis normalization from orchestration.
10. [ ] Extract diagnostics builder only if it reduces duplicated summary/artifact shaping.
11. [x] Keep `WatchlistOrchestrationService` as coordinator facade.

### Tests/checks
- `tests/test_watchlist_orchestration_policy.py`
- `tests/test_proposals.py`
- `tests/test_ticker_deep_analysis.py`
- full backend suite

### Done when
- Main orchestration service is smaller and easier to audit.
- No behavior drift without spec change.

## Phase 5 — Quality/policy surface consolidation

### Tasks
1. Inventory all frontend/backend consumers of calibration/reliability/policy summaries.
2. Make one top-level policy-health payload the default for operator views.
3. Keep low-level calculators as internal facets or focused API/debug contracts.
4. Remove duplicated frontend status derivation.

### Tests/checks
- `tests/test_recommendation_quality_summary.py`
- `tests/test_routes.py` research/quality route tests
- frontend typecheck

### Done when
- Operator-facing policy health has one canonical payload and wording.

## Phase 6 — Redesign-doc archival

### Tasks
1. Merge stable active redesign content into current docs.
2. Archive historical redesign docs.
3. Update `docs-index.md` links.

### Done when
- Current architecture can be understood without reading `docs/redesign/`.

---

# Risk controls

## Avoid unsafe simplification

Do not remove:
- broker audit records
- effective outcome fallback behavior
- warning/degraded diagnostics
- route compatibility needed by UI/tests/scripts
- raw payload visibility used for debugging

## Avoid cosmetic-only refactors

A refactor is worth doing only if it improves at least one of:
- testability of trading logic
- correctness of outcome/reconciliation semantics
- operator diagnosability
- removal of duplicate code paths
- doc/source-of-truth clarity

## Regression protocol

For every implementation phase:

1. Update/normalize the relevant spec first.
2. Add tests for the intended simplified contract.
3. Migrate one consumer at a time.
4. Run targeted tests.
5. Run full backend test suite.
6. Run frontend typecheck.
7. Commit with a message naming the simplification boundary.

---

# Success criteria

This plan is complete when:

- Active docs clearly separate current behavior from target behavior.
- The roadmap contains priorities, not shipped implementation detail.
- Redesign docs are no longer required reading for the active architecture.
- Every major abstraction has a named business question or is archived/removed.
- Outcome resolution has a small explicit engine aligned with its spec.
- `WatchlistOrchestrationService` is materially smaller and behavior remains covered by tests.
- Operator-facing policy/reliability health has one canonical payload.
- Full backend tests and frontend typecheck pass.

## Final expected state

The project remains auditable and safe, but becomes easier to reason about:

- fewer duplicated interpretation paths
- smaller active documentation surface
- clearer current-vs-target claims
- more testable trading logic
- less temptation to add another abstraction for every new diagnostic
