# Remediation plan for post-remediation full audit — 2026-05-29

**Status:** current behavior
**Source audit:** `full-project-spec-code-audit-2026-05-29-post-remediation.md`
**Owner:** Aurelio

## Implementation status

Implemented in commits from `a90a96d` through `0ad231c`.

This record turns every issue from the post-remediation audit into concrete implementation tasks. Each phase followed the project rule:

1. update the relevant spec first
2. translate the spec into focused tests
3. implement code
4. run validation
5. commit and push before starting the next phase

## Phase 1 — Broker exposure safety for `closing` positions

**Addresses:** A4, A5

### Goal
Do not understate live exposure while a broker close request is pending, and do not mark local positions `closing` after rejected close responses.

### Spec tasks
- [ ] Update `docs/broker-position-lifecycle-spec.md` to state that `closing` is still active market exposure until broker fill/reconciliation confirms closure.
- [ ] Update `docs/broker-risk-management-spec.md` and `docs/account-risk-state-spec.md` to include `closing` in open exposure/risk counts.
- [ ] Update `docs/broker-position-steering-spec.md` to define accepted close-response statuses and rejected/unsafe statuses.
- [ ] State that steering must not submit duplicate close-now actions for already-`closing` positions.

### Test tasks
- [ ] Add/extend risk-manager tests proving `closing` positions count in:
  - `open_position_count`
  - `app_open_position_count`
  - `open_notional_usd`
  - projected open exposure with a new candidate
- [ ] Add repository test proving `BrokerPositionRepository.list_active()` includes `closing` where callers need exposure visibility, or add an explicit `list_exposure_active()` and test it.
- [ ] Extend steering workflow tests proving already-`closing` positions are not close-now candidates.
- [ ] Extend `tests/test_order_execution.py`:
  - accepted close response marks local position `closing`
  - rejected/failed close response does not mark local position `closing`
  - raw rejected response remains observable without pretending lifecycle changed

### Implementation tasks
- [ ] Include `BrokerPositionStatus.CLOSING` in risk exposure active statuses.
- [ ] Decide whether to change `list_active()` globally or add a narrower exposure-active repository method; prefer a narrower method if steering active-candidate semantics differ from risk exposure semantics.
- [ ] Add `OrderExecutionService._close_response_accepted()` using explicit accepted statuses/status codes.
- [ ] Call `_mark_position_close_submitted()` only for accepted close responses.
- [ ] Preserve observability events for rejected close responses.
- [ ] Confirm steering duplicate-close prevention still excludes `closing` positions from mutation.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_order_execution.py tests/test_broker_steering_workflow.py tests/test_repositories.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Risk cannot omit pending-close exposure.
- [ ] Local lifecycle cannot move to `closing` after a rejected close response.
- [ ] Steering cannot duplicate a close request for an already-`closing` position.

## Phase 2 — Autonomy evidence semantics and policy threshold correctness

**Addresses:** A1, A2

### Goal
Make the autonomy gate match its spec and remove ambiguity between effective confidence and paper-exploration actionability.

### Spec tasks
- [ ] Update `docs/plan-policy-evaluator-spec.md` to make one explicit decision:
  - **autonomy/policy evidence uses `effective_confidence_threshold()`**, and
  - paper-exploration actionability is a separate cohort, not policy-selected evidence.
- [ ] Update `docs/edge-validation-standard.md` with explicit `PolicyTrustReport` fields for:
  - baseline comparison summary
  - max drawdown summary
  - loss-streak summary
  - missing-input reason codes for each when unavailable
- [ ] Update `docs/operator-page-field-guide.md` to explain that policy-selected evidence excludes low-confidence paper-exploration records.
- [ ] Update `docs/plan-generation-tuning-spec.md` to state automatic promotion must pass baseline/drawdown/loss-streak inputs; manual promotion posture must be explicit.

### Test tasks
- [ ] Add/extend `PlanPolicyEvaluator` tests proving selected outcomes use `effective_confidence_threshold()`, including paper account mode where `action_confidence_threshold() == 0`.
- [ ] Add policy-trust tests for missing:
  - baseline comparison input
  - drawdown input
  - loss-streak input
- [ ] Add edge-gate tests proving missing baseline/drawdown/loss-streak inputs block `eligible_for_cautious_expansion`.
- [ ] Add edge-gate tests proving supplied passing baseline/drawdown/loss-streak inputs allow eligibility when all other criteria pass.
- [ ] Add tuning tests proving auto-promotion is rejected when these trust inputs are missing or failing.

### Implementation tasks
- [ ] Change `PlanPolicyEvaluator._selected_by_policy()` to use `policy.effective_confidence_threshold()` for policy evidence.
- [ ] If paper-mode actionability metrics are still useful, expose them under an explicit `paper_exploration_*` or `actionability_*` diagnostic, not as policy-selected evidence.
- [ ] Add baseline-comparison computation to `PolicyTrustReportService`, reusing existing simple-baseline services where possible.
- [ ] Add drawdown/loss-streak computation over selected effective outcomes.
- [ ] Extend `EdgeValidationGateReport` and `EdgeValidationGateService.evaluate()` with:
  - `baseline_advantage_passed`
  - `max_drawdown_breached`
  - `loss_streak_breached`
  - missing/failure reason codes
- [ ] Wire expanded trust report through dashboard, recommendation-quality, research, and tuning.
- [ ] Update frontend types if new trust fields are rendered or exposed.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_policy_trust_report.py tests/test_edge_validation_gate.py tests/test_repositories.py tests/test_plan_generation_tuning.py tests/test_recommendation_quality_summary.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Policy evidence no longer admits low-confidence paper-exploration plans as selected outcomes.
- [ ] The edge gate cannot pass without explicit baseline, drawdown, and loss-streak evidence.
- [ ] Specs, tests, and UI/API naming agree on policy-vs-paper evidence.

## Phase 3 — Provider observability migration

**Addresses:** A3

### Goal
Make provider failure observability real, uniform, and visible in operator status.

### Spec tasks
- [ ] Update `docs/observability-spec.md` with a transition rule:
  - normalized provider lifecycle events are canonical
  - legacy aggregate events may be emitted temporarily as compatibility diagnostics
- [ ] Define required payload fields for provider attempts:
  - provider
  - source_type
  - ticker/topic
  - mode
  - as_of/window
  - attempt
  - duration_ms
  - status/reason
  - article/count metadata where applicable
- [ ] Update `docs/news-provider-reliability-spec.md` and `docs/news-provider-eligibility-spec.md` to reference normalized provider events.
- [ ] Update `docs/operator-page-field-guide.md` to explain dashboard provider-failure counts.

### Test tasks
- [ ] Extend `tests/test_provider_observability.py` for started/succeeded/failed/skipped payload shapes.
- [ ] Extend news-service tests proving each provider attempt emits normalized events for success, failure, and skip.
- [ ] Add route/dashboard tests proving operator status provider failures count events emitted by real news workflows.
- [ ] Add compatibility test proving legacy `provider.news_fetch_finished` does not double-count when normalized events exist.

### Implementation tasks
- [ ] Inject/use `ProviderObservabilityService` in `NewsIngestionService`.
- [ ] Emit normalized events around each provider attempt instead of only one aggregate finished event.
- [ ] Keep `provider.news_fetch_finished` only as a temporary aggregate compatibility event, or remove it if no consumer requires it.
- [ ] Add normalized events for direct market-data and market-intelligence provider calls where they have clear provider boundaries.
- [ ] Replace `_provider_failure_summary()` grouping by raw payload with a provider/source/status aggregation.
- [ ] Return dashboard provider summary fields:
  - `failed_request_count`
  - `skipped_request_count`
  - `providers_with_failures`
  - `recent_failure_reasons`

### Validation
- [ ] `.venv/bin/pytest -q tests/test_provider_observability.py tests/test_news_service.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Dashboard provider failures reflect provider events actually emitted by live workflows.
- [ ] Provider diagnostics no longer require interpreting unrelated payload schemas.

## Phase 4 — Effective-outcome evaluated-time correctness

**Addresses:** A7

### Goal
Make `evaluated_after` / `evaluated_before` mean effective outcome evaluation time, not plan creation time.

### Spec tasks
- [ ] Update `docs/effective-plan-outcome-spec.md` to define ordering and filtering by effective `evaluated_at`.
- [ ] Update `docs/plan-reliability-report-spec.md` to state reliability windows use effective evaluated time.
- [ ] Update `docs/recommendation-plan-resolution-spec.md` if any raw simulated outcome wording conflicts.

### Test tasks
- [ ] Add regression test seeding:
  - many newer plans with no matching evaluated outcomes
  - older plans resolved recently by broker positions
  - older plans resolved recently by simulated outcomes
  - assert `list_outcomes(evaluated_after=..., limit=...)` returns the recently evaluated older outcomes
- [ ] Add tests for ordering by effective `evaluated_at` descending.
- [ ] Add tests for broker-preferred ordering when broker and simulation both exist.
- [ ] Add calibration/reliability summary test proving a time window includes recently evaluated old plans.

### Implementation tasks
- [ ] Rework `EffectivePlanOutcomeRepository.list_outcomes()` candidate selection.
- [ ] Prefer SQL-side candidate ids for evaluated-time windows:
  - broker positions by `exit_filled_at` / `updated_at`
  - simulated outcomes by `evaluated_at`
  - plan fallbacks by `computed_at` only when no broker/simulation exists
- [ ] Merge candidate ids, hydrate effective outcomes, then sort by effective `evaluated_at` descending.
- [ ] Keep result limits bounded and deterministic.
- [ ] Document any remaining bounded-scan behavior in code comments and specs.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_repositories.py tests/test_recommendation_quality_summary.py tests/test_dashboard_trends.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Effective-outcome time windows cannot miss recently evaluated older plans behind newer unresolved plans.
- [ ] Calibration/reliability windows are aligned with the spec.

## Phase 5 — Real broker steering evidence builder

**Addresses:** A6

### Goal
Move steering thesis invalidation from pre-seeded payloads and warning-string fallback to a production read model built at steering time.

### Spec tasks
- [ ] Update `docs/broker-position-steering-spec.md` with a canonical `BrokerSteeringEvidence` contract:
  - ticker
  - computed_at
  - source signal/plan ids
  - confidence/actionability
  - latest market-intelligence status/conflicts
  - latest ticker/news warnings
  - current price and volatility proxy
  - freshness status
  - missing/stale flags
  - severe-invalidation reason codes
- [ ] Define which missing/stale fields block live mutation vs only require manual review.
- [ ] Define long/short direction-specific invalidation semantics.

### Test tasks
- [ ] Add tests for evidence builder using latest `TickerSignalSnapshot` and latest relevant plan.
- [ ] Add tests for market-intelligence conflicts triggering invalidation only when fresh and ticker-specific.
- [ ] Add tests for stale evidence preventing live thesis-invalidation mutation.
- [ ] Add tests for missing evidence causing conservative keep/manual-review decisions.
- [ ] Add tests for long and short severe-invalidation reason codes.
- [ ] Keep compatibility fallback tests for old plan warning strings, but mark them fallback-only.

### Implementation tasks
- [ ] Add `BrokerSteeringEvidenceBuilder` in `src/trade_proposer_app/services/`.
- [ ] Source latest signal/plan payloads from repositories instead of expecting `steering_evidence` to already exist.
- [ ] Extract market-intelligence conflict flags and warnings from current analysis payloads.
- [ ] Add volatility proxy from latest historical market bars.
- [ ] Extend `BrokerSteeringState` with evidence fields or nested evidence payload.
- [ ] Update `BrokerSteeringStateBuilder` to call the evidence builder.
- [ ] Use evidence as the primary severe-invalidation path; keep plan-warning strings only as compatibility fallback.
- [ ] Ensure broker ownership/reconciliation uncertainty still blocks live mutation regardless of evidence.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_broker_steering_workflow.py tests/test_broker_position_steering.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Steering severe invalidation is based on fresh assembled evidence, not mainly warning-string heuristics.
- [ ] Missing/stale evidence blocks risky live mutations while preserving safe expiry cancellation.

## Phase 6 — Market-intelligence UI/settings clarity

**Addresses:** A9

### Goal
Prevent disabled market-intelligence payloads from being interpreted as active evidence.

### Spec tasks
- [ ] Update `docs/market-intelligence-analysis-spec.md` with exact disabled-payload display rules.
- [ ] Update `docs/recommendation-methodology.md` to state disabled market intelligence contributes no evidence.
- [ ] Decide and document whether a settings/API/UI toggle is in scope now. If not, explicitly keep it target behavior.

### Test tasks
- [ ] Add ticker/deep-analysis tests proving disabled snapshots contribute zero confidence and are labeled disabled.
- [ ] Add route/API tests if ticker payloads expose market-intelligence coverage status.
- [ ] Add frontend type expectations for `coverage_status` where rendered.

### Implementation tasks
- [ ] Carry `coverage_status` and `freshness_status` through ticker payload/frontend types.
- [ ] Update ticker page labels:
  - disabled → “Market intelligence disabled”
  - unavailable/stale → warning/neutral status
  - active/fresh → evidence label
- [ ] Avoid adding disabled market-intelligence summaries to action narratives as if they were evidence.
- [ ] If settings are added, wire `MarketIntelligenceServiceConfig.enabled` through settings repository, API, and UI; otherwise leave service disabled-by-default with explicit UI status.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_market_intelligence.py tests/test_ticker_deep_analysis.py tests/test_routes.py`
- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Operators can distinguish disabled market intelligence from active supportive/conflicting evidence.
- [ ] Disabled market-intelligence payloads never lift confidence or narrative strength.

## Phase 7 — Simulated diagnostic naming in frontend/API

**Addresses:** A8

### Goal
Make simulation-only entry/actionability diagnostics unmistakable in operator-facing UI.

### Spec tasks
- [ ] Update `docs/effective-plan-outcome-spec.md` with the compatibility-alias removal plan.
- [ ] Update `docs/operator-page-field-guide.md` for recommendation-quality wording.
- [ ] Update `docs/raw-details-reference.md` with current payload keys.

### Test tasks
- [ ] Extend backend tests proving both compatibility and canonical keys exist while compatibility remains.
- [ ] Add frontend typecheck-backed type updates for `simulated_entry_miss_diagnostics`.
- [ ] Add or update UI tests if available for recommendation-quality labels; otherwise keep typecheck and route tests.

### Implementation tasks
- [ ] Update `frontend/src/types.ts` to include:
  - `simulated_entry_miss_diagnostics`
  - `simulated_actionability_diagnostics` where relevant
  - `policy_trust` if rendered/consumed
- [ ] Update `frontend/src/pages/recommendation-quality-page.tsx` to read the simulated key first.
- [ ] Change labels/helper copy to say “simulated entry misses” and “simulation-only diagnostics”.
- [ ] Keep old `entry_miss_diagnostics` as backend alias for compatibility, but stop using it as the primary frontend source.
- [ ] Add TODO/removal note with a concrete future removal condition or date.

### Validation
- [ ] `.venv/bin/pytest -q tests/test_recommendation_quality_summary.py tests/test_routes.py`
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit`
- [ ] `.venv/bin/pytest -q`
- [ ] `.venv/bin/python -m alembic heads`
- [ ] `git diff --check`

### Done when
- [ ] Recommendation-quality UI no longer presents simulation-only diagnostics under ambiguous names.
- [ ] Compatibility aliases are documented as temporary.

## Phase 8 — Docs status reconciliation

**Addresses:** A10

### Goal
Remove stale active-plan ambiguity from docs and make completed records obvious.

### Spec/doc tasks
- [ ] Convert `docs/audits/full-project-spec-code-audit-2026-05-29-remediation-plan.md` from task checklist to completed implementation record, or mark every completed task as done.
- [ ] Update `docs/docs-index.md` so completed remediation records are not described as active plans.
- [ ] Review audit docs with missing/non-standard status labels:
  - `docs/audits/abstraction-inventory-2026-05.md`
  - `docs/audits/full-project-spec-code-audit-2026-05-09.md`
  - `docs/audits/full-project-spec-code-audit-2026-05-10-post-watchlist-refactor.md`
  - `docs/audits/full-project-spec-code-audit-2026-05-10.md`
  - `docs/audits/project-spec-code-coherence-audit-2026-05-09.md`
- [ ] Either mark old audit docs as `reference` or move/archive them if they are historical only.
- [ ] Ensure every active doc uses one allowed status label:
  - `current behavior`
  - `target behavior`
  - `current + target behavior`
  - `active plan`
  - `reference`

### Test/validation tasks
- [ ] Add or run a lightweight docs-status check script if one exists; otherwise use a shell status scan.
- [ ] Run `git diff --check`.

### Implementation tasks
- [ ] Edit docs only; do not change app code in this phase.
- [ ] Keep historical audit content intact unless moving to archive.
- [ ] Update index pointers after any moves.

### Validation
- [ ] `for f in docs/*.md docs/audits/*.md; do ... status scan ...; done`
- [ ] `git diff --check`
- [ ] Optional: `.venv/bin/pytest -q tests/test_routes.py::RouteTests::test_docs_page...` if docs browser route tests are affected.

### Done when
- [x] This document is a completed implementation record, not an active plan.
- [x] Completed remediation docs read as completed records.
- [x] Active docs have allowed status labels only.

## Final full validation after all phases

Run before declaring the plan complete:

```bash
.venv/bin/pytest -q
cd frontend && ./node_modules/.bin/tsc --noEmit
.venv/bin/python scripts/check_postgres_validation.py
.venv/bin/python -m alembic heads
git diff --check
```

If `POSTGRES_TEST_DATABASE_URL` is not set, record the explicit skip message. If a Postgres test URL is available, the script must upgrade to Alembic head and run the Postgres integration suite successfully.

## Completion criteria

This plan is complete only when:

- broker `closing` positions are risk-counted and close rejection handling is safe
- policy evidence threshold semantics match specs and tests
- edge gate cannot pass without baseline/drawdown/loss-streak evidence
- provider failure dashboard metrics are based on real normalized provider events
- effective-outcome windows are evaluated-time correct
- steering severe invalidation uses fresh assembled evidence
- disabled market intelligence is visibly disabled and contributes no evidence
- simulation-only diagnostics are labeled as such in frontend and API docs
- docs/index status is coherent
- all final validation commands pass or documented Postgres skip is explicit
