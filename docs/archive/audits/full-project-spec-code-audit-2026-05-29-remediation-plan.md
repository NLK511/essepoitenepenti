# Remediation plan for full project spec/code audit — 2026-05-29

**Status:** current behavior
**Source audit:** `full-project-spec-code-audit-2026-05-29.md`
**Owner:** Aurelio

## Implementation status

Completed in commits:

- `aa9c9a7` — canonical policy trust report, effective/raw outcome labeling and paging, broker steering run-status aggregation, local close-position lifecycle marker.
- `0484cd0` — fresh steering evidence fallback, market-intelligence current-status reconciliation, Postgres validation script, settings cleanup.
- `315afa0` — normalized provider observability helper and dashboard provider-failure summary.

Validation after implementation:

```text
.venv/bin/pytest -q
653 passed, 3 skipped

cd frontend && ./node_modules/.bin/tsc --noEmit
passed

.venv/bin/python scripts/check_postgres_validation.py
POSTGRES_TEST_DATABASE_URL is not set; skipping Postgres validation.

.venv/bin/python -m alembic heads
0042_merge_broker_heads (head)

git diff --check
clean
```

This plan turns each audit finding into concrete tasks. Each implementation phase must follow the project rule:

1. update the relevant spec first
2. translate the spec into tests
3. implement code
4. run validation
5. commit and push

## Phase 1 — Canonical policy trust report

**Addresses:** A1, A2, I1, R1

### Goal
Make `edge_validation_gate` the authoritative autonomy gate and make every UI/API surface use one shared trust assembly.

### Spec tasks
- [ ] Update `docs/edge-validation-standard.md` with a `PolicyTrustReport` contract containing:
  - `edge_validation_gate`
  - `policy_health_headline`
  - `policy_evaluation`
  - `reliability_report`
  - `walk_forward_validation`
  - `evidence_concentration`
  - `degraded_input_summary`
  - `broker_reconciliation_summary`
  - explicit `missing_inputs`
- [ ] Update `docs/plan-policy-evaluator-spec.md` to state `policy_health` is a derived headline, not the autonomy gate.
- [ ] Update `docs/operator-page-field-guide.md` to say dashboard/research trust labels come from the same report.

### Test tasks
- [ ] Add `tests/test_policy_trust_report.py`.
- [ ] Test that missing walk-forward input produces an explicit missing/rejection reason.
- [ ] Test that missing concentration input produces an explicit missing/rejection reason.
- [ ] Test that broker reconciliation uncertainty reaches the edge gate.
- [ ] Test that `policy_health_headline` is derived from the edge gate / policy evidence and cannot contradict the authoritative gate.
- [ ] Extend route tests for `/api/dashboard/operator-status` to assert the full trust report shape.
- [ ] Extend research/quality route tests if they expose policy trust data.

### Implementation tasks
- [ ] Add `src/trade_proposer_app/services/policy_trust_report.py`.
- [ ] Move edge-gate input assembly out of dashboard/tuning/quality routes into the new service.
- [ ] Update `src/trade_proposer_app/api/routes/dashboard.py` to use the shared service.
- [ ] Update `src/trade_proposer_app/services/recommendation_quality_summary.py` to use the shared service.
- [ ] Update `src/trade_proposer_app/services/plan_generation_tuning.py` to use the shared service for auto-promotion gate checks.
- [ ] Keep backward-compatible keys temporarily where the frontend expects them.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_policy_trust_report.py tests/test_routes.py tests/test_recommendation_quality_summary.py tests/test_plan_generation_tuning.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Dashboard, recommendation-quality, research, and tuning use the same trust report.
- [ ] The edge gate never silently omits required spec inputs.
- [ ] `policy_health` is clearly subordinate to the edge gate.

## Phase 2 — Effective vs raw outcome semantic cleanup

**Addresses:** A4, A5, I1, R1

### Goal
Make broker-preferred effective outcomes unambiguous, and clearly label simulated-only diagnostics.

### Spec tasks
- [ ] Update `docs/effective-plan-outcome-spec.md` with naming rules:
  - effective metrics use `effective_*` or documented headline names
  - raw simulated diagnostics use `simulated_*`
  - compatibility endpoints must state when they return effective vs raw data
- [ ] Update `docs/raw-details-reference.md` with effective/raw payload distinctions.
- [ ] Update `docs/operator-page-field-guide.md` for dashboard/recommendation-quality wording.

### Test tasks
- [ ] Add regression tests in `tests/test_effective_plan_outcomes.py` or `tests/test_repositories.py` for filtered cohort undercount:
  - seed many recent unmatched plans
  - seed older matching resolved outcomes
  - assert `list_outcomes(outcome=..., resolved=..., limit=...)` returns the matching rows
- [ ] Extend `tests/test_routes.py` for `/api/recommendation-outcomes/actionability-diagnostics` response naming.
- [ ] Extend `tests/test_dashboard_trends.py` or dashboard route tests to assert simulated-only diagnostics are labeled as such.
- [ ] Extend `tests/test_recommendation_quality_summary.py` to assert raw simulated diagnostics are not presented as effective outcomes.

### Implementation tasks
- [ ] Fix `EffectivePlanOutcomeRepository.list_outcomes()` to avoid post-limit filtering bias:
  - push simple filters into SQL where possible, or
  - fetch in pages until enough filtered results are collected, with a bounded scan limit.
- [ ] Rename response keys:
  - `entry_miss_diagnostics` → `simulated_entry_miss_diagnostics`
  - `actionability` diagnostic payloads → `simulated_actionability_diagnostics`
- [ ] Keep temporary compatibility aliases if frontend still reads old keys.
- [ ] Update frontend types and labels if API keys change.
- [ ] Audit `RecommendationOutcomeRepository` consumers and document each as raw-only or migrate to effective outcomes.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_repositories.py tests/test_routes.py tests/test_recommendation_quality_summary.py tests/test_dashboard_trends.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Effective outcome metrics and simulated diagnostics cannot be confused in API/UI payloads.
- [ ] Narrow filtered cohorts are not biased by recent unmatched plans.

## Phase 3 — Broker steering execution status and close lifecycle

**Addresses:** A6, A8

### Goal
Make broker steering run summaries accurately reflect what happened, and mark local lifecycle state immediately after close-position submission.

### Spec tasks
- [ ] Update `docs/broker-position-steering-spec.md` with run-level execution statuses:
  - `dry_run`
  - `no_action`
  - `blocked`
  - `partial_success`
  - `succeeded`
  - `failed`
- [ ] Update `docs/broker-position-lifecycle-spec.md` with close submission semantics:
  - close-now accepted by broker creates/updates local state to `closing` or `close_submitted`
  - final `win`/`loss` still comes from reconciliation/fill evidence
- [ ] Update `docs/observability-spec.md` with steering mutation result event expectations.

### Test tasks
- [ ] Extend `tests/test_broker_steering_workflow.py`:
  - all live decisions blocked → run summary `execution_status == "blocked"`
  - mixed blocked/succeeded → `partial_success`
  - no candidates/actionable mutations → `no_action`
  - dry run remains `dry_run`
- [ ] Extend `tests/test_order_execution.py`:
  - `close_position()` accepted by broker updates local broker position to `closing`/`close_submitted`
  - raw close response/order id is persisted when available
  - final closed status is not faked as win/loss before reconciliation

### Implementation tasks
- [ ] Change `BrokerSteeringService.run_once()` to aggregate final per-decision execution statuses after execution attempts.
- [ ] Persist and return accurate run-level `execution_status`.
- [ ] Add local lifecycle update in `OrderExecutionService.close_position()`.
- [ ] If needed, add a broker-position status constant for `closing` / `close_submitted` and migration-safe handling.
- [ ] Update frontend steering status labels if new statuses appear.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_broker_steering_workflow.py tests/test_order_execution.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Run status no longer says `submitted` when every decision was blocked.
- [ ] Close-now creates immediate local audit evidence without pretending the trade is resolved.

## Phase 4 — Broker steering fresh evidence read model

**Addresses:** A7, I3

### Goal
Move steering thesis invalidation from warning-string heuristics to a compact current-evidence read model.

### Spec tasks
- [ ] Update `docs/broker-position-steering-spec.md` with `BrokerSteeringEvidence` fields:
  - latest signal id / computed_at
  - latest plan/actionability/confidence
  - latest market-intelligence coverage/conflicts
  - latest ticker/news warnings
  - volatility proxy
  - stale/missing flags
  - evidence freshness cutoff
- [ ] Define which missing evidence blocks live mutation vs only reduces confidence.
- [ ] Define exact severe-invalidation reason codes.

### Test tasks
- [ ] Add tests for severe invalidation from latest ticker/signal evidence.
- [ ] Add tests for market-intelligence conflict causing invalidation only when fresh and ticker-specific.
- [ ] Add tests for stale evidence not triggering live mutation.
- [ ] Add tests for missing evidence producing conservative keep/manual-review decisions.
- [ ] Add tests for long and short direction-specific invalidation.

### Implementation tasks
- [ ] Add `BrokerSteeringEvidenceBuilder` or extend `BrokerSteeringStateBuilder` with explicit evidence assembly.
- [ ] Pull latest relevant `TickerSignalSnapshot`, latest plan metadata, market-intelligence payloads, and warning diagnostics.
- [ ] Add volatility proxy from latest market bars.
- [ ] Replace `_has_severe_negative_news(plan)` as the primary invalidation path; keep it only as compatibility fallback.
- [ ] Ensure broker ownership/reconciliation uncertainty still overrides evidence and blocks live mutation.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_broker_steering_workflow.py tests/test_broker_position_steering.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Steering can explain thesis invalidation from fresh evidence, not just plan warning strings.
- [ ] Missing/stale evidence is visible and conservative.

## Phase 5 — Market-intelligence current-status reconciliation

**Addresses:** A3, I2, ambiguous market-intelligence behavior

### Goal
Decide and document whether market intelligence is a disabled experimental layer or a production decision input, then make code/settings match.

### Decision point
Choose one:

- **Option A: keep disabled/experimental** until canonical snapshot persistence exists.
- **Option B: enable as configurable bounded input** with settings, UI, and explicit provider diagnostics.

### Spec tasks
- [ ] Update `docs/market-intelligence-analysis-spec.md` current behavior section:
  - service exists
  - yfinance-backed partial implementation exists
  - default is disabled
  - no canonical snapshot persistence yet
  - replay uses unavailable/degraded behavior without stored snapshots
- [ ] Update `docs/recommendation-methodology.md` to stop calling it purely future work.
- [ ] If Option B, update `docs/news-provider-eligibility-spec.md` or add a small provider-policy section for yfinance/Finnhub/etc.

### Test tasks
- [ ] If Option A:
  - test disabled snapshots are clearly marked `disabled`
  - test disabled snapshots do not increase confidence
  - test UI/API does not present disabled market intelligence as evidence
- [ ] If Option B:
  - add settings repository/domain/API tests for market-intelligence enablement
  - add frontend type tests via TypeScript
  - add deep-analysis tests proving enabled data is bounded and conflict-aware
  - add replay tests proving no live fetch for historical as-of

### Implementation tasks
- [ ] If Option A:
  - ensure disabled market-intelligence payloads cannot create support/confidence
  - improve labels in payload/UI if needed
- [ ] If Option B:
  - add settings keys under `market_intelligence.*`
  - expose settings in Settings API/UI
  - pass settings into `MarketIntelligenceServiceConfig`
  - add provider diagnostics and error visibility
- [ ] Do not add canonical persistence until separately specified and migrated.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_market_intelligence.py tests/test_ticker_deep_analysis.py tests/test_proposals.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Docs and code agree on whether market intelligence is active, disabled, or experimental.
- [ ] It cannot silently inflate confidence when disabled or stale.

## Phase 6 — Provider lifecycle observability unification

**Addresses:** I4, observability gaps

### Goal
Make provider failures diagnosable across processes with one structured event shape.

### Spec tasks
- [ ] Update `docs/observability-spec.md` with provider lifecycle event schema:
  - `provider.request_started`
  - `provider.request_succeeded`
  - `provider.request_failed`
  - `provider.request_skipped`
  - fields: provider, source_type, ticker/topic, as_of/window, replay/live mode, attempt, duration, reason, correlation/run/job ids
- [ ] Update `docs/news-provider-reliability-spec.md` with mapping from retry/fallback outcomes to events.
- [ ] Update `docs/data-quality-audit-spec.md` if repeated provider failures should appear in data-quality summaries.

### Test tasks
- [ ] Add tests for news provider attempts emitting normalized events.
- [ ] Add tests for market-data fetch fallback emitting normalized events.
- [ ] Add tests for market-intelligence provider unavailable emitting normalized events.
- [ ] Add route tests that operator-status or observability API exposes repeated provider failures.

### Implementation tasks
- [ ] Add a small provider event helper service to avoid duplicated payload construction.
- [ ] Wire it into news, market data, market intelligence, and broker provider calls where practical.
- [ ] Add aggregated provider-failure counts to dashboard operator-status.
- [ ] Keep raw provider diagnostics in detailed payloads; only aggregate compact status in dashboard.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_news_service.py tests/test_ticker_deep_analysis.py tests/test_market_intelligence.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

### Done when
- [ ] Operators can see repeated provider failures without reading workflow-specific payloads.
- [ ] Provider diagnostics have consistent event names and fields.

## Phase 7 — Postgres validation hardening

**Addresses:** I5

### Goal
Reduce risk that SQLite-only local validation misses production-like database regressions.

### Spec tasks
- [ ] Update `docs/getting-started.md` or `docs/operational-scripts-reference.md` with a Postgres validation command.
- [ ] Update `docs/archive/implementation-plans/audit-remediation-and-autonomy-readiness-plan.md` with Postgres validation as a release checklist item.

### Test/tasks
- [ ] Add or update a script, e.g. `scripts/check_postgres_validation.py`, that:
  - requires `POSTGRES_TEST_DATABASE_URL`
  - runs Alembic upgrade head
  - runs focused Postgres integration tests
  - exits with a clear skip message if not configured
- [ ] Add a smoke test for the script behavior if practical.

### Implementation tasks
- [ ] Keep default local tests deterministic and not dependent on a running Postgres.
- [ ] Add CI/deployment docs for when Postgres validation must be run.

### Validation
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `.venv/bin/pytest -q tests/test_postgres_integration.py` when `POSTGRES_TEST_DATABASE_URL` is available
- [ ] `.venv/bin/pytest -q`
- [ ] `git diff --check`

### Done when
- [ ] There is a documented, repeatable Postgres validation path.
- [ ] Skipped Postgres coverage is explicit, not accidental.

## Phase 8 — Targeted architecture cleanup

**Addresses:** R2, R3, R4, ambiguity items

### Goal
Reduce semantic drift in large modules only after behavior fixes are locked by tests.

### Candidate seams
- [ ] Extract effective-outcome filtering/paging helper from repository after Phase 2 tests pass.
- [ ] Extract steering evidence assembly from workflow after Phase 4 tests pass.
- [ ] Extract provider event payload builder after Phase 6 tests pass.
- [ ] Split `MarketIntelligenceService` provider access from scoring only if Option B is chosen.
- [ ] Remove duplicate `@staticmethod` in `SettingsDomainService`.
- [ ] Tighten type hints for services that accept `EffectivePlanOutcomeRepository` but name `RecommendationOutcomeRepository`.

### Guardrails
- [ ] No refactor without parity tests first.
- [ ] No new abstraction unless it deletes duplicated behavior or clarifies a spec boundary.
- [ ] Keep compatibility wrappers for existing route/test callers during migration.

### Validation
- [ ] Focused tests for touched seam
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `git diff --check`

## Cross-phase acceptance checklist

Before marking the audit remediated:

- [ ] every finding A1–A8 has either a shipped fix or a documented explicit deferral
- [ ] every incomplete item I1–I5 has either a shipped fix or an owner/target status
- [ ] every redundancy R1–R4 has either reduced surface area or clear canonical ownership
- [ ] docs use approved status labels only
- [ ] backend tests pass
- [ ] frontend typecheck passes
- [ ] Alembic has one head
- [ ] `git diff --check` is clean
- [ ] commit and push after each completed phase
