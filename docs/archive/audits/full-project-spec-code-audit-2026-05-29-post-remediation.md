# Full project spec/code audit — 2026-05-29 post-remediation

**Status:** reference
**Auditor:** Aurelio
**Scope:** active specs, backend services/repositories/routes, frontend type surface, tests, and the post-remediation changes through commit `ba24e53`.

## Validation performed

```text
.venv/bin/pytest -q
653 passed, 3 skipped

cd frontend && ./node_modules/.bin/tsc --noEmit
passed

.venv/bin/python -m alembic heads
0042_merge_broker_heads (head)

git diff --check
clean
```

Static shape checked during audit:

```text
51 active docs under docs/
147 backend Python files under src/trade_proposer_app
58 backend test files
largest services: proposals.py 1654 lines, taxonomy.py 1611, news.py 1488, ticker_deep_analysis.py 1262, plan_generation_tuning.py 1158, event_extraction.py 1112, order_execution.py 1065, job_execution.py 1065, industry_context.py 1063
```

## Executive verdict

The previous remediation removed the biggest immediate ambiguity around policy trust, simulated diagnostics, broker steering run status, and close-position lifecycle visibility. The app is safer and more coherent than the prior audit snapshot.

The remaining risk is now more specific: several specs describe production-grade shared contracts, but some implementations are still compatibility adapters, partial read models, or instrumentation helpers that are not wired through the real workflows. The app remains suitable for human-supervised research and paper trading; it still should not be treated as an autonomous money-making bot.

## High-priority spec/code inconsistencies

### A1 — Edge gate spec requires baseline/drawdown/loss-streak checks, but the gate does not compute them

**Specs involved:** `edge-validation-standard.md`, `plan-policy-evaluator-spec.md`.

**Code involved:**
- `src/trade_proposer_app/services/edge_validation_gate.py`
- `src/trade_proposer_app/services/plan_policy_evaluator.py`
- `src/trade_proposer_app/services/policy_trust_report.py`

**Finding:** The edge-validation spec says the gate must evaluate baseline comparison, max drawdown, and loss streak. `EdgeValidationGateService` currently uses absolute win-rate/P&L/profit-factor checks and labels `baseline_underperformance` when selected win rate is below 50%, not when it underperforms an explicit baseline. Drawdown and loss-streak fields are not represented in `PlanPolicyEvaluation`, `PolicyTrustReport`, or `EdgeValidationGateReport`.

**Impact:** The gate is conservative for current weak evidence, but the implementation does not yet satisfy the stated autonomy standard. If future data improves, the gate could become eligible without actually proving baseline advantage or drawdown control as specified.

**Remediation:** Add explicit baseline, drawdown, and loss-streak inputs to `PolicyTrustReport` and `EdgeValidationGateService`. Until implemented, update the conformance section to state these are missing required inputs that block expansion.

### A2 — Plan policy evaluator spec says effective threshold; code uses action threshold that becomes zero in paper mode

**Specs involved:** `plan-policy-evaluator-spec.md`, `edge-validation-standard.md`.

**Code involved:**
- `src/trade_proposer_app/services/plan_policy_evaluator.py`
- `src/trade_proposer_app/services/trade_decision_policy.py`
- `tests/test_repositories.py`

**Finding:** The spec says selected outcomes require confidence >= `TradeDecisionPolicy.effective_confidence_threshold()`. Code uses `policy.action_confidence_threshold()`, which returns `0.0` in paper exploration mode. Current tests expect paper-mode behavior, not the spec language.

**Impact:** Active policy evaluation and edge-gate evidence can include low-confidence paper-exploration plans as selected outcomes. This can distort policy health and promotion readiness, especially because dashboard and tuning now consume the canonical trust report.

**Remediation:** Decide whether policy evaluation is measuring operator actionability or paper exploration. If it is autonomy evidence, use `effective_confidence_threshold()` and add a separate paper-exploration cohort. If paper exploration remains intentional, update the spec and UI labels to say selected outcomes include all paper-mode plans.

### A3 — Provider observability spec names normalized lifecycle events, but live news providers still emit a different aggregate event

**Specs involved:** `observability-spec.md`.

**Code involved:**
- `src/trade_proposer_app/services/provider_observability.py`
- `src/trade_proposer_app/services/news.py`
- `src/trade_proposer_app/api/routes/dashboard.py`

**Finding:** `ProviderObservabilityService` emits `provider.request_started/succeeded/failed/skipped`, but it is not wired into the real provider paths. `NewsIngestionService` still records `provider.news_fetch_finished` with aggregate diagnostics. Dashboard operator status counts only `provider.request_failed`, so it will not reflect current news-provider failures.

**Impact:** The newly added dashboard provider-failure summary can read as zero even when news provider diagnostics report failures. Cross-provider observability remains split between normalized helper events and legacy aggregate news events.

**Remediation:** Wire `ProviderObservabilityService` into news, market data, market intelligence, broker-provider calls where useful, and migrate dashboard summaries to read either normalized events only after migration or both schemas during transition.

### A4 — Broker risk and active-position queries exclude `closing` positions

**Specs involved:** `broker-position-lifecycle-spec.md`, `broker-risk-management-spec.md`, `account-risk-state-spec.md`.

**Code involved:**
- `src/trade_proposer_app/services/risk_management.py`
- `src/trade_proposer_app/repositories/broker_positions.py`
- `src/trade_proposer_app/services/broker_position_steering_workflow.py`

**Finding:** `closing` means a close request has been submitted but final fill/P&L evidence has not arrived. It is still market exposure. `risk_management.OPEN_STATUSES` and `BrokerPositionRepository.list_active()` only include `submitted` and `open`.

**Impact:** A position in `closing` can be omitted from app-side open exposure metrics before reconciliation confirms the close. This can understate open position count/notional and weaken risk checks.

**Remediation:** Treat `closing` as active exposure for risk metrics, while keeping steering from issuing duplicate close actions against already-closing positions. Add tests proving risk counts `closing` and steering skips it for mutation.

### A5 — Close-position lifecycle marker is written for any returned close response, not only accepted/safe close responses

**Specs involved:** `broker-position-lifecycle-spec.md`, `broker-position-steering-spec.md`.

**Code involved:** `src/trade_proposer_app/services/order_execution.py`.

**Finding:** `_mark_position_close_submitted()` marks a position `closing` after `client.close_position()` returns a result. It does not verify that the returned status/status_code indicates broker acceptance rather than rejection or an unsupported/terminal state.

**Impact:** A rejected close response that is returned rather than raised could incorrectly hide an open position behind `closing`.

**Remediation:** Define accepted close statuses and HTTP statuses in the spec, add tests for rejected close responses, and only mark local lifecycle `closing` when the broker response is accepted/submitted/queued/fill-pending.

### A6 — Steering evidence freshness is documented, but there is no producer for `steering_evidence`

**Specs involved:** `broker-position-steering-spec.md`.

**Code involved:**
- `src/trade_proposer_app/services/broker_position_steering_workflow.py`
- `src/trade_proposer_app/services/watchlist_signal_builder.py`
- `src/trade_proposer_app/services/watchlist_plan_framing.py`

**Finding:** The workflow can read `plan.signal_breakdown["steering_evidence"]` and reject stale evidence. Tests seed that payload directly. No production builder currently writes this compact payload into plans/signals.

**Impact:** Severe thesis invalidation still usually falls back to warning-string heuristics. The spec and tests make the path look more complete than runtime behavior.

**Remediation:** Add a `BrokerSteeringEvidenceBuilder` that assembles latest signal, plan, market-intelligence conflicts, news/ticker warnings, confidence/actionability, volatility proxy, and freshness flags. Wire it into steering state building instead of relying on pre-seeded payloads.

### A7 — Effective outcome repository still orders by plan time, which can miss recently evaluated older plans

**Specs involved:** `effective-plan-outcome-spec.md`, `plan-reliability-report-spec.md`.

**Code involved:** `src/trade_proposer_app/repositories/effective_plan_outcomes.py`.

**Finding:** `list_outcomes()` pages plans ordered by `RecommendationPlanRecord.computed_at`, then constructs effective outcomes and applies `evaluated_after/evaluated_before` in Python. A broker position or simulation outcome evaluated recently for an older plan can be missed if enough newer plans exist before it.

**Impact:** Time-windowed calibration, policy evaluation, reliability, and dashboard summaries can undercount recently resolved older plans. The previous paging fix reduced one bias but did not make evaluated-time filtering canonical.

**Remediation:** Implement SQL-side candidate selection for evaluated-time windows across broker positions, simulated outcomes, and plan fallbacks, or build a materialized effective-outcome query/view that orders by effective `evaluated_at`.

### A8 — Recommendation-quality API/UI still expose old `entry_miss_diagnostics` naming as the primary frontend path

**Specs involved:** `effective-plan-outcome-spec.md`, `operator-page-field-guide.md`.

**Code involved:**
- `src/trade_proposer_app/services/recommendation_quality_summary.py`
- `frontend/src/types.ts`
- `frontend/src/pages/recommendation-quality-page.tsx`

**Finding:** Backend now also returns `simulated_entry_miss_diagnostics`, but it still returns `entry_miss_diagnostics`. Frontend types and labels consume the old key and do not label the section as simulation-only.

**Impact:** Operators can still confuse broker-preferred effective performance with raw/simulated entry-miss diagnostics.

**Remediation:** Update frontend types and UI copy to use/display `simulated_entry_miss_diagnostics`. Keep the old key only as a documented compatibility alias until a later removal.

### A9 — Market intelligence is disabled by default but still shapes payloads and frontend labels

**Specs involved:** `market-intelligence-analysis-spec.md`, `recommendation-methodology.md`.

**Code involved:**
- `src/trade_proposer_app/services/market_intelligence.py`
- `src/trade_proposer_app/services/proposals.py`
- `src/trade_proposer_app/services/ticker_deep_analysis.py`
- `frontend/src/pages/ticker-page.tsx`

**Finding:** The spec now correctly says market intelligence is disabled by default and not production decision-grade. The code still injects disabled neutral snapshots into analysis contexts, and UI labels show "Market intelligence" without clearly distinguishing disabled vs unavailable vs active evidence.

**Impact:** Operators may think market intelligence was considered as live evidence when it was only a disabled neutral payload.

**Remediation:** Surface `coverage_status` in the UI and plan narrative, and avoid showing disabled snapshots as evidence. Add settings only when the provider/persistence policy is ready.

### A10 — Post-remediation plan doc is marked current behavior but still contains unchecked task boxes

**Specs/docs involved:**
- `docs/archive/audits/full-project-spec-code-audit-2026-05-29-remediation-plan.md`
- `docs/docs-index.md`

**Finding:** The remediation plan has an implementation-status header saying completed, but its phase checklists remain unchecked. `docs/docs-index.md` still describes it as an active task plan.

**Impact:** The docs give contradictory signals about whether the previous plan is complete.

**Remediation:** Convert the remediation plan into an implementation record: mark phase tasks done or replace checklists with completed summaries. Update the docs index so this plan is no longer listed as active.

## Incomplete implementation against target specs

1. **Autonomy evidence completeness:** baseline, drawdown, loss-streak, and full degraded-input sourcing are not yet first-class inputs to the gate.
2. **Provider observability:** normalized provider lifecycle exists as a helper and test, but not as the actual provider event contract.
3. **Broker steering analytics:** current steering can mutate safely in simple cases, but thesis invalidation is still not rebuilt from fresh market/news/signal evidence.
4. **Market intelligence:** no persisted snapshot table, settings/API/UI toggle, provider eligibility wiring, or replay-safe stored history.
5. **Postgres assurance:** `scripts/check_postgres_validation.py` exists, but validation remains opt-in unless `POSTGRES_TEST_DATABASE_URL` is set.
6. **Frontend trust visibility:** the API exposes full `policy_trust`, but the dashboard strip only renders headline labels/reasons and not the full missing-input/readiness shape.

## Redundant or over-complex implementation

1. **Provider diagnostics have two event schemas:** normalized `ProviderObservabilityService` and news-specific `provider.news_fetch_finished`.
2. **Market-intelligence plumbing is wider than its production readiness:** disabled snapshots pass through proposal/deep-analysis/transmission/narrative/UI surfaces.
3. **Recommendation-quality payload carries both old and new simulated diagnostic keys:** useful for compatibility, but currently indefinite.
4. **Large multi-role services remain risk areas:** `proposals.py`, `news.py`, `ticker_deep_analysis.py`, `plan_generation_tuning.py`, `event_extraction.py`, `order_execution.py`, `job_execution.py`, and `industry_context.py` remain the main maintenance risks. Refactor only around tested semantic seams.

## Ambiguous code relative to specs

1. Is policy evaluation supposed to use action threshold or effective threshold? Specs and code disagree.
2. Is a `closing` broker position active exposure? Lifecycle semantics say yes until fill evidence, risk code says no.
3. Is `provider_failures.failed_request_count` an actual operator metric today? It only counts normalized events that live providers do not yet emit.
4. Is disabled market intelligence evidence or just an absence marker? Payloads are persisted like evidence, but the spec says it is not decision-grade.
5. Is manual tuning promotion allowed to bypass the edge gate? The edge spec says automatic promotion is blocked; code also has manual promotion paths whose exact safety posture should be explicit in the tuning spec.
6. Does `EffectivePlanOutcomeRepository.list_outcomes(evaluated_after=...)` mean plan-created window or outcome-evaluated window? The parameter name and specs imply evaluated-time, but ordering/scanning is plan-time.

## Remediation plan

### Phase 1 — Fix autonomy evidence semantics

1. Update `edge-validation-standard.md` and `plan-policy-evaluator-spec.md` to clarify threshold semantics, baseline comparison, drawdown, and loss-streak inputs.
2. Add tests proving policy evaluation selects by the chosen threshold semantics.
3. Add baseline/drawdown/loss-streak fields to the trust report or mark them as explicit missing inputs that block expansion.
4. Wire dashboard/recommendation-quality/tuning to the expanded trust report.

### Phase 2 — Correct broker exposure safety around `closing`

1. Update broker lifecycle/risk specs to state whether `closing` counts as exposure.
2. Add risk-manager tests for `closing` position count/notional.
3. Add close-position rejection tests.
4. Count `closing` as active exposure for risk, but keep steering duplicate-close prevention.
5. Mark local position `closing` only after accepted close responses.

### Phase 3 — Make provider observability real

1. Update `observability-spec.md` with a migration rule for legacy aggregate provider events.
2. Wire `ProviderObservabilityService` into `NewsIngestionService` provider attempts.
3. Add normalized provider events for market data/market intelligence where calls are direct and diagnosable.
4. Update dashboard provider summary to aggregate by provider/source/status and test it against real emitted events.

### Phase 4 — Build real steering evidence

1. Replace the ad-hoc `steering_evidence` payload expectation with a documented `BrokerSteeringEvidenceBuilder`.
2. Source latest ticker signal, plan metadata, market-intelligence conflicts, news warnings, confidence/actionability, current price, volatility, and freshness.
3. Make missing/stale evidence block live thesis-invalidation mutations while still allowing expiry cancellation.
4. Add long/short and stale/fresh tests.

### Phase 5 — Make effective-outcome windows truly evaluated-time based

1. Add regression tests with old plans resolved recently behind many newer plans.
2. Rework `EffectivePlanOutcomeRepository.list_outcomes()` so evaluated-time filters and ordering are based on effective outcome time, not plan computed time.
3. Keep bounded limits, but make truncation explicit if a bounded scan remains.

### Phase 6 — Finish simulated-diagnostic naming in frontend/UI

1. Update frontend types to include `simulated_entry_miss_diagnostics` and `policy_trust`.
2. Update recommendation-quality copy to label entry-miss/actionability diagnostics as simulated-only.
3. Keep old keys as compatibility aliases for one documented window, then remove or hide them from primary UI usage.

### Phase 7 — Reconcile docs status and stale active plans

1. Convert completed remediation plans into implementation records with checked/completed status.
2. Update `docs/docs-index.md` so completed records are not described as active plans.
3. Review old audit docs with missing/non-standard status labels and either archive them or mark as reference.

## Suggested execution order

1. Phase 2 first for broker exposure safety.
2. Phase 1 next because it controls autonomy/promotion semantics.
3. Phase 3 because current dashboard provider failures are misleading.
4. Phase 5 to protect performance statistics from cohort/time-window bias.
5. Phase 4, then Phase 6, then Phase 7.

Each phase should follow the project rule: spec update, tests, implementation, validation, commit, and push.
