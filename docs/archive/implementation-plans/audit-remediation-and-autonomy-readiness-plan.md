# Audit remediation and autonomy readiness plan

**Status:** archived implementation history

This archived record captured the umbrella audit-remediation plan after the 2026-05-10 project audit. Current production/autonomy gates now live in `../../production-readiness-plan.md`, `../../recommendation-quality-improvement-plan.md`, and `../../specs/edge-validation-standard.md`.

It covers safety, evidence, observability, docs coherence, migration confidence, and the last major simplification seams.

## Goal

Make the platform safe and honest enough to expand autonomy only when evidence justifies it.

## Audit concerns this plan must close

1. no binding edge-validation/autonomy gate
2. broker/app reconciliation drift is not a halt-enforced safety loop
3. Postgres/Alembic validation is skipped by default
4. `policy_health` is not a prominent operator control
5. plan-generation tuning target guardrails are only partially implemented
6. mixed current/target docs still create cognitive load
7. broker-risk wording conflicts with implementation around manual halt semantics
8. watchlist deletion referential-integrity coverage is weak
9. partial-persistence semantics are underspecified
10. observability is missing some structured lifecycle coverage
11. `TickerDeepAnalysisService` and `ProposalService` still carry mixed responsibilities

## Working rules

- Spec first, then code.
- Add parity tests before moving persisted/operator-facing payload logic.
- Preserve compatibility wrappers until tests/callers migrate.
- Do not increase autonomy before the edge gate and broker drift gate are binding.
- Do not add new abstractions unless they remove duplication, isolate a safety invariant, or shrink a large service around a testable seam.

## Workstreams

### 1. Edge validation and autonomy gate

Purpose: make “can we trust this policy?” a hard decision instead of a narrative.

Deliverables:
- [x] `docs/edge-validation-standard.md`
- [x] a broker-backed minimum sample requirement
- [x] baseline comparison rules
- [x] expected-value / profit-factor thresholds
- [x] max drawdown and loss-streak limits
- [x] out-of-sample and walk-forward stability rules
- [x] setup-family and regime concentration limits
- [x] demotion/halt rules when live results degrade

Acceptance criteria:
- [x] plan-generation promotion cannot happen unless the standard passes
- [x] no current broker autonomy-scope expansion setting exists; any future setting must use the same gate before it ships
- [x] the standard is visible in operator-facing docs and UI
- [x] failing the standard produces a clear halt or demotion reason

### 2. Broker reconciliation and halt loop

Purpose: prevent app/broker drift from becoming silent exposure.

Deliverables:
- [x] persisted broker account/order/position snapshots or an equivalent reconciliation ledger
- [x] drift classification by severity in pre-submit live snapshot checks
- [x] block new submissions when broker state is uncertain or materially divergent in pre-submit live snapshot checks
- [x] explicit semantics for cancel/liquidate/hold on halt

Acceptance criteria:
- the app can explain whether it trusts current broker state
- drift and unknown-state conditions block new autonomous submissions
- operator review can see why the halt happened

### 3. Postgres and migration validation

Purpose: stop shipping migration assumptions that only hold in SQLite.

Deliverables:
- [x] required Postgres/Alembic smoke validation in CI or release flow
- [x] a documented minimal Postgres test path
- [x] migration upgrade-to-head coverage in the default validation path

Acceptance criteria:
- a migration break cannot hide behind a skipped integration suite
- CI documents how Postgres validation is enforced

### 4. Operator-facing policy health

Purpose: make the highest-level trust signal obvious.

Deliverables:
- [x] add `policy_health` to frontend types
- [x] render a top-level Research/Quality card or equivalent headline
- [x] include label, reasons, sample size, broker-outcome share, and recommended stance

Acceptance criteria:
- policy health is the first thing an operator sees when judging trust
- lower-level calibration and validation views remain available as drill-downs

### 5. Spec and docs coherence cleanup

Purpose: remove mixed-scope confusion from active docs.

Deliverables:
- [x] split or clearly conform `plan-generation-tuning-spec.md`
- [x] split or clearly conform `recommendation-plan-resolution-spec.md`
- [x] amend `broker-risk-management-spec.md` wording around manual halt semantics
- [x] update `architecture.md` and `recommendation-methodology.md` for the latest extracted services
- [x] keep active plan docs current in `docs/docs-index.md`

Acceptance criteria:
- every active doc has one obvious status
- current behavior and target behavior are distinguishable at section level
- manual halt semantics are unambiguous

### 6. Data integrity and observability hardening

Purpose: make failures visible and keep persisted truth coherent.

Deliverables:
- [x] fix watchlist deletion referential-integrity coverage
- [x] define partial-persistence semantics for failed runs
- [x] add structured observability coverage for broker lifecycle events
- [x] ensure broker lifecycle events include run/job ids where the data allows it
- [x] add structured observability coverage for provider lifecycle events
- [x] ensure correlation ids are available where the data allows it beyond run/job-linked broker events

Acceptance criteria:
- integrity failures are tested against the target datastore behavior
- partial artifacts have a clear validity rule
- operator logs/events are enough to reconstruct broker/provider failures

### 7. Safe service simplification

Purpose: continue reducing cognitive load only where seams are clear.

Priority seams:
- `TickerDeepAnalysisService`
- `ProposalService`
- `NewsIngestionService`
- `TaxonomyService`
- `RecommendationPlanEvaluationService`
- `JobExecutionService`

Rules:
- extract one seam at a time
- add parity tests before changing persisted payload construction
- keep wrappers only while a migration is active
- stop if the remaining code is already clear enough

Acceptance criteria:
- large services shrink through tested seams, not speculative decomposition
- no new abstraction is kept just because it is smaller

## Execution order

### Phase 0 — stop the known gaps
1. [x] write the edge-validation standard
2. [x] clarify broker-risk/manual-halt semantics
3. [x] add `policy_health` to the frontend
4. [x] update docs that still mix current and target behavior

### Phase 1 — bind the safety loop
1. [x] implement persisted broker reconciliation snapshots/drift classes
2. [x] add pre-submit block behavior for uncertain or divergent live broker state
3. [x] require Postgres/Alembic validation in the normal path

### Phase 2 — harden the evidence path
1. [x] codify partial-persistence semantics
2. [x] strengthen provider observability events and broader correlation coverage
3. [x] fix integrity tests against target datastore behavior

### Phase 3 — simplify only where seams are obvious
1. continue extracting from `TickerDeepAnalysisService`
2. continue extracting from `ProposalService`
3. remove temporary compatibility wrappers only after tests/callers migrate

## Non-goals

- no microservices rewrite
- no new summary-of-summary abstraction
- no autonomy expansion before the edge gate passes
- no refactor that weakens persisted/operator-visible truth
- no abstraction added only to reduce line count

## Completion criteria

This plan is complete when:

- edge validation is a binding gate for autonomy
- broker drift can halt the system safely
- Postgres migration validation is required, not optional
- policy health is prominent in the UI
- active docs are unambiguous about current vs target behavior
- data integrity and observability failures are explicit and test-backed
- remaining large services are only simplified around clear seams
