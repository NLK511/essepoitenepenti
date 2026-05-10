# Lean architecture and docs reconciliation plan

**Status:** active plan

This is the short active plan for keeping the architecture and docs lean after the May 2026 cleanup. Completed implementation history has been moved to `docs/archive/implementation-plans/`.

## Goal

Keep the app easier to reason about without weakening trading safety, auditability, degraded-input visibility, or calibration truth.

## Current state

Completed history is archived:
- `archive/implementation-plans/p0-p4-remediation-plan-2026-05.md`
- `archive/implementation-plans/p3-p4-audit-remediation-plan-2026-05.md`
- `archive/implementation-plans/architecture-simplification-refactor-plan-2026-05.md`

The active codebase now has dedicated services for shortlist selection, watchlist execution, cheap-scan/deep-analysis normalization, signal construction, plan framing, plan narrative/evidence/risk text, calibration review, transmission payloads, decision samples, outcome resolution, effective outcomes, risk management, settings domains, and complex workbench read models.

## Remaining active work

### 1. Normalize active doc statuses

Problem: active docs still use several status forms such as `canonical reference`, `active`, `active v1`, and `authoritative implementation spec`.

Target: every active doc should clearly be one of:
- current behavior
- target behavior
- active plan
- reference

Acceptance:
- `docs/docs-index.md` remains the single navigation guide.
- No completed implementation record is listed as current-state reading.
- Specs with mixed current/target content include an explicit conformance section.

### 2. Split or relabel mixed current/target specs

Highest-priority docs:
- `plan-generation-tuning-spec.md`
- `recommendation-plan-resolution-spec.md`

Target:
- make shipped behavior vs target autonomous behavior obvious at section level, or split into current and target docs.

### 3. Keep `policy_health` as the operator quality headline

Problem: calibration, baselines, reliability, evidence concentration, setup-family review, walk-forward validation, signal gating, and plan-generation tuning are all useful but mentally expensive.

Target:
- `policy_health` should be the first answer to “is the active selection policy healthy enough to trust or expand?”
- Lower-level reports should remain drill-down/debug facets.

### 4. Add a binding edge-validation/autonomy gate

Problem: the app can summarize outcomes and tune settings, but it still lacks a hard standard for declaring a trading edge.

Target:
- create an edge-validation standard covering minimum broker-backed sample size, baseline comparison, expected value/profit factor, drawdown/loss-streak limits, and out-of-sample stability.
- use that standard before increasing autonomy.

### 5. Harden broker reconciliation before autonomy

Problem: the risk manager checks current app-ledger and optional live snapshots, but broker drift is not yet a first-class halt condition.

Target:
- persist broker account/order/position snapshots.
- classify app-vs-broker drift severity.
- halt new autonomous submissions when broker state is uncertain.

### 6. Add default or CI Postgres migration validation

Problem: Postgres integration tests are currently skipped unless `POSTGRES_TEST_DATABASE_URL` is configured.

Target:
- add an Alembic/Postgres smoke path in default CI or a documented required release gate.

### 7. Continue architecture simplification only around clear seams

Current largest simplification candidates:
- `ProposalService`
- `TickerDeepAnalysisService`
- `NewsIngestionService`
- `TaxonomyService`
- `RecommendationPlanEvaluationService`
- `JobExecutionService`

Rules:
- do not create a new abstraction unless it removes duplicated code, isolates a trading-safety invariant, or shrinks a large service around a testable behavior.
- preserve compatibility wrappers only as temporary migration aids.
- update parity tests before moving persisted/operator-facing payload logic.

## Non-goals

- Do not remove broker/effective outcome audit history.
- Do not hide degraded input diagnostics.
- Do not collapse domain boundaries that protect trading safety.
- Do not rewrite the app into microservices.
- Do not add summary-of-summary services unless they replace existing surfaces.

## Regression protocol

For behavior-changing simplification:
1. update the relevant spec first
2. add or update tests for the intended contract
3. migrate one consumer at a time
4. run targeted backend tests
5. run full backend tests
6. run frontend typecheck
7. run `git diff --check`

## Completion criteria

This active plan is complete when:
- active docs no longer carry completed implementation-plan history
- current-vs-target behavior is obvious in every active spec
- edge validation and broker drift halt rules are binding before autonomy expands
- operator-facing policy/risk/data-quality health has one prominent status surface
- large services are only refactored through clear, tested seams
