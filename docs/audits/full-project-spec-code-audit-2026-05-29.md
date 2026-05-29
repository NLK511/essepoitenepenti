# Full project spec/code audit — 2026-05-29

**Status:** reference
**Auditor:** Aurelio
**Scope:** active specs, backend services/repositories/routes, frontend type surface, tests, docs/code coherence, incomplete/redundant implementation, and ambiguity that can affect autonomous trading safety.

## Validation performed

```text
.venv/bin/pytest -q
644 passed, 3 skipped

cd frontend && ./node_modules/.bin/tsc --noEmit
passed

.venv/bin/python -m alembic heads
0042_merge_broker_heads (head)
```

Static shape checked during audit:

```text
49 active docs under docs/
145 backend Python files under src/trade_proposer_app
56 backend test files
largest services: proposals.py 1654 lines, taxonomy.py 1611, news.py 1488, ticker_deep_analysis.py 1262, plan_generation_tuning.py 1159, event_extraction.py 1112, job_execution.py 1065, industry_context.py 1063, order_execution.py 1047
```

## Executive verdict

The app is coherent as a human-supervised research, diagnostics, paper-execution, broker-risk, and calibration platform. It is not yet coherent as a fully autonomous money-making bot because the evidence gates, broker reconciliation semantics, and operator trust surfaces are still split across parallel read models.

Recent work materially improved broker execution safety: broker risk gates, effective outcomes, edge validation, and broker steering exist and are tested. The biggest remaining risk is now semantic drift: multiple services answer similar trust questions with different thresholds and different evidence inputs.

## High-priority spec/code inconsistencies

### A1 — `edge_validation_gate` and `policy_health` are parallel trust signals

**Specs involved:** `edge-validation-standard.md`, `plan-policy-evaluator-spec.md`, `features-and-capabilities.md`.

**Code involved:**
- `src/trade_proposer_app/services/edge_validation_gate.py`
- `src/trade_proposer_app/services/trade_policy_evaluation.py`
- `src/trade_proposer_app/api/routes/dashboard.py`
- `src/trade_proposer_app/services/recommendation_quality_summary.py`

**Finding:** `EdgeValidationGateService` is the canonical autonomy gate, but `TradePolicyEvaluationSummary.policy_health` also labels trust using looser thresholds. Dashboard operator status returns both, yet calls the edge gate without walk-forward validation, evidence concentration readiness, degraded-input share, or broker reconciliation certainty.

**Impact:** operators can see contradictory labels: a policy can look merely `watch` or `healthy` in one surface while the autonomy gate is `research_only` or `blocked`. This is safe in the conservative direction for autonomy, but ambiguous for operator decisions.

**Remediation:** keep `policy_health` only as a headline summary, but build it from the edge-gate report or label it explicitly as non-authoritative. Add one `PolicyTrustReport` adapter that always includes edge gate, policy evaluation, reliability report, walk-forward, concentration, degraded-input share, and reconciliation certainty.

### A2 — Dashboard edge gate is underfed relative to its spec

**Specs involved:** `edge-validation-standard.md`.

**Code involved:** `src/trade_proposer_app/api/routes/dashboard.py`.

**Finding:** `/api/dashboard/operator-status` constructs `EdgeValidationGateService().evaluate(policy_review.policy_evaluation)` with only the policy evaluation. The spec says the gate must evaluate walk-forward stability, concentration, degraded inputs, and broker-reconciliation certainty.

**Impact:** missing inputs show as `None` instead of explicit rejection reasons. The gate remains conservative on sample/broker/P&L thresholds, but the status does not fully explain why autonomy should not expand.

**Remediation:** reuse the same trust assembly used by recommendation-quality/tuning. If an input cannot be computed cheaply, return explicit reason codes such as `walk_forward_input_missing`, `concentration_input_missing`, and `broker_reconciliation_input_missing` rather than `None`.

### A3 — Market-intelligence docs lag shipped partial implementation

**Specs involved:** `market-intelligence-analysis-spec.md`, `recommendation-methodology.md`.

**Code involved:**
- `src/trade_proposer_app/services/market_intelligence.py`
- `src/trade_proposer_app/services/ticker_deep_analysis.py`
- `src/trade_proposer_app/services/proposals.py`
- `src/trade_proposer_app/services/watchlist_transmission.py`

**Finding:** the spec says there is not yet a dedicated market-intelligence layer, but code now has a `MarketIntelligenceService`, payload integration, bounded confidence contribution, tests, and transmission/narrative plumbing. However it is disabled by default, lacks settings/API/UI toggles, and does not persist canonical market-intelligence snapshot records.

**Impact:** current behavior is unclear: the layer exists but is mostly inert in production. Developers may either overtrust it as fully shipped or ignore it as only planned.

**Remediation:** update the spec to say current behavior is a disabled-by-default yfinance-backed experimental layer with no canonical snapshot table. Add settings if it should be used live; otherwise keep it test-only and explicitly mark it not part of production decision quality.

### A4 — Effective-outcome contract is mostly implemented, but raw simulated diagnostics still leak into summary surfaces

**Specs involved:** `effective-plan-outcome-spec.md`.

**Code involved:**
- `src/trade_proposer_app/repositories/effective_plan_outcomes.py`
- `src/trade_proposer_app/api/routes/recommendation_outcomes.py`
- `src/trade_proposer_app/api/routes/dashboard.py`
- `src/trade_proposer_app/services/recommendation_quality_summary.py`

**Finding:** calibration, setup-family review, evidence concentration, dashboard profit/win-rate, tuning, and policy evaluation generally use `EffectivePlanOutcomeRepository`. But actionability/entry-miss diagnostics still read `RecommendationOutcomeRepository` without always labeling that they are simulation-only diagnostics.

**Impact:** operator-facing summaries can mix effective broker-preferred P&L with simulated-only entry-miss/actionability details. This is useful but semantically ambiguous.

**Remediation:** rename exposed fields to `simulated_entry_miss_diagnostics` / `simulated_actionability_diagnostics`, or implement effective-aware actionability diagnostics and keep raw diagnostics under an explicitly raw endpoint.

### A5 — Effective outcome repository applies pre-filter limits before all semantic filters

**Specs involved:** `effective-plan-outcome-spec.md`, `plan-reliability-report-spec.md`.

**Code involved:** `src/trade_proposer_app/repositories/effective_plan_outcomes.py`.

**Finding:** `list_outcomes()` fetches recent plans with `limit * 5`, then applies outcome/setup/resolved/evaluated filters in Python. This can undercount filtered cohorts when there are many recent unmatched plans.

**Impact:** calibration, reliability, concentration, and gate reports can be sample-biased under high plan volume or narrow filters.

**Remediation:** move filters that can be SQL-side into the query, or overfetch in pages until the requested filtered limit is filled. Add regression tests with many unmatched recent plans before older matching resolved outcomes.

### A6 — Broker steering run-level execution status is ambiguous

**Specs involved:** `broker-position-steering-spec.md`, `observability-spec.md`.

**Code involved:** `src/trade_proposer_app/services/broker_position_steering_workflow.py`.

**Finding:** individual steering decisions persist `dry_run`, `blocked`, `succeeded`, or `failed`, but `BrokerSteeringRunSummary.execution_status` is set to `submitted` whenever steering is enabled and not dry-run, even if every decision is blocked or unsupported.

**Impact:** run summaries can imply live submission occurred when only blocked decisions were recorded.

**Remediation:** aggregate decision execution statuses after processing. Use run-level statuses like `dry_run`, `no_action`, `blocked`, `partial_success`, `succeeded`, `failed`. Keep per-decision status as the source of truth.

### A7 — Broker steering state still uses sparse thesis-invalidation inputs

**Specs involved:** `broker-position-steering-spec.md`.

**Code involved:** `src/trade_proposer_app/services/broker_position_steering_workflow.py`.

**Finding:** v1 state building now has latest stored daily close as a price proxy and reconciliation health from latest ticker snapshot, but severe invalidation is still inferred from plan warning strings only. Fresh ticker analysis, market-intelligence evidence, volatility, current actionability, and explicit thesis-rationale decay are not yet rebuilt at steering time.

**Impact:** steering is operationally conservative but not yet analytically complete. It can cancel expired orders and manage obvious price/exit cases, but it cannot reliably detect thesis decay except where warning strings happen to contain expected tokens.

**Remediation:** add a bounded steering evidence refresh read model: latest signal/plan context, latest ticker/news/market-intelligence warnings, current confidence/actionability, volatility proxy, and explicit stale/missing flags. Keep mutation blocked when evidence is missing.

### A8 — Close-position broker mutation does not immediately update local position lifecycle state

**Specs involved:** `broker-position-steering-spec.md`, `broker-position-lifecycle-spec.md`.

**Code involved:** `src/trade_proposer_app/services/order_execution.py`.

**Finding:** `close_position()` submits a broker close and emits observability events, but does not immediately write a local broker-position transition such as `closing` or link the resulting broker close order. The ledger depends on later sync/reconciliation to reflect closure.

**Impact:** after a steering close-now action, the app may temporarily show an open position despite a close request being accepted. This can confuse steering/risk loops and operators.

**Remediation:** persist a local lifecycle marker (`closing`/`close_submitted`) and raw broker close response, then let reconciliation finalize win/loss once fills arrive.

## Incomplete implementation against target specs

### I1 — Edge gate inputs exist in pieces, not as one canonical gate assembly

Required inputs include drawdown/loss-streak, baseline comparison, walk-forward, concentration, degraded-input share, and broker reconciliation. Code computes many of these separately, but there is no shared assembler used by dashboard, tuning, research, and future autonomy settings.

### I2 — Market intelligence lacks canonical persistence and settings

The service can produce snapshots, but there is no snapshot table, no as-of replay history, no provider eligibility wiring, and no UI/settings contract. Therefore it should remain a bounded experimental evidence modifier, not a proven production signal.

### I3 — Broker reconciliation is strong enough for pre-submit checks, but not a full account/fill reconciliation engine

Specs correctly state this as a current limitation. The code persists snapshots and blocks on material/uncertain drift when a live snapshot is supplied, but account activity/fill reconciliation and post-submit broker-led lifecycle correction remain incomplete.

### I4 — Provider lifecycle observability is still uneven

News, market data, broker sync, and run events all have diagnostics, but provider-attempt events are not uniformly structured across providers and workflows. Cross-process diagnosis still requires reading different payload formats.

### I5 — Postgres validation remains optional outside local manual runs

The suite passes on the configured environment and Alembic has one head, but Postgres integration tests remain opt-in. Production-like JSON/datetime/index behavior can still regress if not run separately.

## Redundant or over-complex implementation

### R1 — Trust/readiness surfaces overlap

`policy_health`, `edge_validation_gate`, recommendation-quality status, evidence-concentration `ready_for_expansion`, walk-forward `promotion_recommended`, and tuning `promotion_eligible` all answer adjacent questions. They should remain separate calculators but converge into one operator contract.

### R2 — Legacy/new analysis boundary is still broad

`ProposalService`, `TickerDeepAnalysisService`, `TickerAnalysisPayloadService`, watchlist services, and market-intelligence wiring overlap in context/enrichment/payload responsibility. The boundary is better than before, but adding more payload fields without central schemas will increase drift.

### R3 — Large multi-role modules remain maintenance risks

The biggest risks are `proposals.py`, `taxonomy.py`, `news.py`, `ticker_deep_analysis.py`, `plan_generation_tuning.py`, `event_extraction.py`, `job_execution.py`, `industry_context.py`, and `order_execution.py`. Refactor only around tested seams that remove duplicated semantics, not line count alone.

### R4 — Settings domain has small cleanup debt

`SettingsDomainService` has a duplicated `@staticmethod` decorator before `_optional_bool`. This is harmless at runtime but signals low-level cleanup debt in a central configuration service.

## Ambiguous code relative to specs

1. `RecommendationWalkForwardValidationService` type hints `RecommendationOutcomeRepository`, but callers pass `EffectivePlanOutcomeRepository` by duck typing. This works but hides the effective-outcome contract from readers.
2. `/api/recommendation-outcomes` is now mostly an effective-outcome compatibility alias, but one subroute is raw simulated actionability diagnostics. Naming should reflect this split.
3. `MarketIntelligenceServiceConfig.enabled` defaults to false, but code still injects neutral/disabled snapshots into analysis payloads. Specs should clarify whether disabled snapshots are expected in persisted payloads.
4. Steering `min_reviewed_dry_run_*` settings count persisted dry-run decisions, not human-reviewed decisions. Docs partly clarify this but setting names remain misleading.
5. Risk assessment with no live broker snapshot returns `broker_drift_severity=not_checked`; pre-submit with a broker client should provide a snapshot, but surfaces that call `assess()` without one should not be interpreted as proof of broker certainty.

## Remediation plan

### Phase 1 — Canonical trust report and dashboard gate correctness

1. Update `edge-validation-standard.md` to define one `PolicyTrustReport` read model.
2. Add tests proving dashboard/operator-status includes walk-forward, concentration, degraded-input, and reconciliation inputs or explicit missing-input reason codes.
3. Implement a shared service used by dashboard, recommendation-quality summary, tuning promotion, and research.
4. Demote `policy_health` to a derived headline inside that report.

### Phase 2 — Effective/raw outcome semantic cleanup

1. Update `effective-plan-outcome-spec.md` with explicit raw-diagnostic naming rules.
2. Add tests for `/api/recommendation-outcomes/actionability-diagnostics` labeling and dashboard/recommendation-quality payload names.
3. Fix `EffectivePlanOutcomeRepository.list_outcomes()` filtering/limit bias with SQL filters or paged overfetch.
4. Add regression tests for filtered cohorts behind many unmatched recent plans.

### Phase 3 — Broker steering observability and lifecycle correctness

1. Update `broker-position-steering-spec.md` with run-level execution-status semantics and close-position local lifecycle semantics.
2. Add tests for all-blocked live steering run summaries and accepted close-now local `closing` marker.
3. Aggregate run execution status from persisted decision results.
4. Persist close-position lifecycle transition immediately after broker close submission.

### Phase 4 — Steering evidence freshness

1. Extend the steering spec state object with explicit current-evidence fields and missing/stale flags.
2. Add tests for severe invalidation from fresh ticker evidence, not only warning strings.
3. Implement a bounded steering evidence builder using latest signal/plan/market-intelligence/news artifacts.
4. Keep live mutation blocked when ownership, quantity, reconciliation, or evidence freshness is uncertain.

### Phase 5 — Market-intelligence status reconciliation

1. Update `market-intelligence-analysis-spec.md` current behavior to match code: disabled-by-default experimental yfinance layer with payload plumbing but no canonical persistence.
2. Decide whether to ship settings/UI enablement or keep disabled until snapshot persistence exists.
3. If enabling, add settings/API/UI tests and a provider eligibility rule.
4. If not enabling, prevent disabled neutral payloads from being mistaken for decision-grade evidence.

### Phase 6 — Observability and provider lifecycle unification

1. Define provider attempt/failure event schema in `observability-spec.md`.
2. Add structured events for news, market-data, market-intelligence, and broker provider attempts.
3. Surface repeated provider failures in the operator-status payload.

### Phase 7 — Architecture cleanup only after semantic fixes

1. Split only high-value seams: market-data retrieval diagnostics, provider attempt logging, effective-outcome filtering, and steering evidence assembly.
2. Avoid new abstraction layers that do not replace existing surfaces.
3. Add parity tests before extracting payload builders or analysis payload logic.

## Recommended execution order

Do not start with broad refactors. The safest order is:

1. Phase 1 trust report
2. Phase 2 effective/raw outcome cleanup
3. Phase 3 broker steering execution-status/lifecycle fixes
4. Phase 4 steering evidence refresh
5. Phase 5 market-intelligence spec/status decision
6. Phase 6 provider observability
7. Phase 7 targeted architecture cleanup

Each phase should follow the project rule: spec update first, tests second, implementation third, validation, then commit/push.
