# Historical playback tuning operating plan

**Status:** active plan

Historical playback tuning has moved from implementation checklist to operating discipline. The durable behavior contract lives in `specs/historical-playback-tuning-spec.md`; completed implementation history belongs in archive if more detail is needed.

## Goal

For each historical `as_of` slice, the system should be able to:

1. load only generation inputs available at or before `as_of`
2. regenerate ticker signals and recommendation plans using current code/settings plus a scoped candidate plan-generation tuning config
3. resolve resulting candidate plans with post-`as_of` bars under canonical plan-resolution semantics
4. compare candidate configs through search, validation, and walk-forward slices
5. promote only when sample quality and edge-validation gates pass

## Current baseline

Implemented baseline:

- point-in-time replay coverage reports across market/news/context/fundamental inputs
- historical news availability filtering through `available_at <= as_of`
- replay execution that can run scan, deep analysis, signal generation, and plan generation for slices
- scoped plan-generation config overrides that do not mutate live settings
- replay outcomes resolved through the canonical plan-resolution path
- replay eligibility records with Tier A/B/C/ineligible semantics
- replay-based tuning modes and replay artifact aggregation
- walk-forward, baseline, concentration, degraded-input, and edge-validation gates for promotion
- operator visibility for tuning mode, evidence tiers, skipped reasons, resolution source, and replay links
- replay-based tuning as the default scheduled/auto tuning path; stored-plan rescore remains diagnostic/manual

## Active operating work

### 1. Evidence quality monitoring

- audit each new replay batch for eligible-row count, unresolved share, phantom dominance, and Tier A/B mix
- reject promotion when replay evidence is too thin, stale, phantom-heavy, or missing provenance
- keep replay evidence-quality artifacts under `artifacts/` so promotion decisions can cite them

### 2. Replay coverage improvement

- improve historical bars, news, context, and fundamental coverage only when it increases point-in-time-safe eligible evidence
- prefer explicit missing/degraded evidence over unsafe live-provider fallback
- keep generation coverage separate from outcome-resolution coverage

### 3. Promotion discipline

- compare candidates against baseline/current config, not just pooled winners
- require walk-forward support before promotion
- keep auto-promotion fail-closed on missing edge, drawdown, loss-streak, concentration, degraded-input, or broker-reconciliation inputs
- keep manual promotion possible only for candidates that pass non-autonomous checks and have clear operator rationale

### 4. Stored-plan rescore containment

- keep `stored_plan_rescore` available for diagnostics/regression
- do not treat compact stored-plan evidence as full replay evidence
- prevent any automatic promotion path from relying on stored-plan rescore alone

### 5. Operator clarity

- keep UI labels explicit about replay mode, evidence tier, outcome population, and resolution source
- link tuning candidates to replay slices/plans/outcomes where possible
- surface why candidates are rejected, especially evidence-quality rejection reasons

## Success criteria

Historical playback tuning is healthy when:

- replay batches produce enough Tier A or explicitly accepted Tier A/B evidence for the question being tested
- every tuning artifact states mode, outcome population, eligibility tier, and promotion readiness
- no replay or tuning path leaks future data into generation inputs
- rejected candidates remain explainable to an operator
- promoted configs beat baseline/current settings in walk-forward checks without unacceptable concentration, drawdown, or degradation regressions

## See also

- `specs/historical-playback-tuning-spec.md`
- `specs/input-access-provenance-remediation-spec.md`
- `specs/plan-generation-tuning-spec.md`
- `specs/edge-validation-standard.md`
- `recommendation-quality-improvement-plan.md`
