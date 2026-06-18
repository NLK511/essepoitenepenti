# Confidence calibration spec

**Status:** implemented for read-time API/service controls; snapshot job remains target behavior

This spec defines how Aurelio computes and inspects confidence calibration across time windows, including operator-controlled inclusion or exclusion of phantom trades. Persisted calibration snapshots remain future work.

## Purpose

Confidence calibration answers:

> When the app says a plan has X% confidence, how often do comparable plans actually win?

Calibration is not the same as signal gating, plan generation tuning, or broker risk management.

- **Signal gating tuning** decides which upstream signals deserve deeper analysis or framing.
- **Plan-generation tuning** decides how downstream trade plans are framed and filtered.
- **Confidence calibration** measures and adjusts whether displayed/used confidence aligns with realized outcomes.

The app already has confidence calibration logic, but operators need more explicit control over:

- calibration time windows
- inclusion/exclusion of phantom outcomes
- execution-only vs opportunity-aware calibration semantics
- stable snapshots for autonomy/audit

## Current implementation snapshot

Implemented today:

- `RecommendationPlanCalibrationService` computes calibration from outcomes at read time.
- Calibration reports include confidence-bin reliability, Brier score, expected calibration error, and smoothed/Bayesian-style reliability curves.
- `WatchlistCalibrationReviewService` builds `calibration_review` payloads used during watchlist plan framing.
- Plan/signal payloads can store:
  - `raw_confidence_percent`
  - `calibrated_confidence_percent`
  - `confidence_adjustment`
  - `effective_confidence_threshold`
  - `calibration_review`
- Calibration review considers cohorts such as setup family, confidence bucket, horizon, transmission bias, context regime, and horizon + setup family.
- Research/API surfaces can compute calibration reports on demand.

Current boundaries:

- Default calibration treats only `win` and `loss` as resolved execution labels.
- Operators can explicitly request phantom-only, mixed execution + phantom, or side-by-side read-time reports.
- Phantom inclusion is never silent: report mode, label policy, source counts, and warnings disclose it.
- Computed-window parameters are accepted and disclosed, but effective-outcome retrieval is still evaluation-time anchored until a plan-computed-time calibration index exists.
- There is no dedicated scheduled calibration job and no persisted calibration snapshot table yet.

## Definitions

### Raw confidence

The original confidence score emitted by analysis/framing before calibration adjustment.

### Calibrated confidence

A bounded confidence score after reliability-bin and cohort review adjustments. It should be treated as an empirical estimate only when evidence is sufficient.

### Execution calibration

Calibration using executed/actionable trade outcomes only:

- `win`
- `loss`

This is the primary calibration mode for broker execution and autonomous trading decisions.

### Phantom/opportunity calibration

Calibration using missed-opportunity labels for non-actionable or non-executed plans:

- `phantom_win`
- `phantom_loss`

This evaluates whether upstream or downstream gates rejected opportunities that later worked or correctly rejected poor opportunities.

### Mixed calibration

A research-only mode that maps both real and phantom outcomes into binary success/failure labels:

- successes: `win`, `phantom_win`
- failures: `loss`, `phantom_loss`

Mixed calibration must not be used for live broker execution confidence unless explicitly validated, because it combines different decision semantics.

## Calibration modes

Operators must be able to select one of these modes.

### `execution_only`

Included labels:

- `win`
- `loss`

Excluded labels:

- `phantom_win`
- `phantom_loss`
- `open`
- `expired`
- `no_action`
- `watchlist`
- unresolved outcomes

Use for:

- live confidence calibration
- broker execution readiness
- autonomy gates
- actionability thresholds

This should remain the default.

### `phantom_only`

Included labels:

- `phantom_win`
- `phantom_loss`

Excluded labels:

- `win`
- `loss`
- unresolved outcomes

Use for:

- missed-opportunity analysis
- signal-gating recall review
- actionability threshold review
- no-action/watchlist evaluation

This must not directly alter broker execution confidence.

### `execution_plus_phantom`

Included labels:

- `win`
- `loss`
- `phantom_win`
- `phantom_loss`

Binary mapping:

- `win` and `phantom_win` count as success
- `loss` and `phantom_loss` count as failure

Use for:

- research comparisons
- broad opportunity-quality diagnostics
- operator experiments

This mode must be clearly labeled as mixed semantics.

### `side_by_side`

Compute and return multiple reports together:

- execution-only calibration
- phantom-only calibration
- mixed calibration

Use for:

- operator review
- dashboard/research pages
- deciding whether phantom evidence agrees with broker/execution evidence

## Time-window controls

Operators must be able to run calibration on explicit windows.

Supported window selectors:

- `evaluated_after`
- `evaluated_before`
- `computed_after`
- `computed_before`
- named relative windows:
  - `7d`
  - `14d`
  - `30d`
  - `90d`
  - `180d`
  - `365d`
  - `all`

Rules:

- Evaluation-window filtering is preferred for calibration because calibration labels become known at `evaluated_at`.
- Computed-window filtering is useful for regime review, but must be clearly labeled because newer plans may not have resolved yet.
- If both evaluated and computed filters are supplied, the report must disclose both filters.
- Time-window boundaries must be timezone-aware and normalized to UTC.
- Reports must show the actual first/last evaluated/computed timestamps included.

## Required report payload

Every calibration run/report should include:

```json
{
  "mode": "execution_only",
  "window": {
    "label": "90d",
    "evaluated_after": "2026-03-20T00:00:00Z",
    "evaluated_before": "2026-06-18T00:00:00Z",
    "computed_after": null,
    "computed_before": null
  },
  "label_policy": {
    "included_outcomes": ["win", "loss"],
    "success_outcomes": ["win"],
    "failure_outcomes": ["loss"],
    "excluded_outcomes": ["phantom_win", "phantom_loss"]
  },
  "summary": {
    "total_outcomes": 1000,
    "included_outcomes": 240,
    "successes": 102,
    "failures": 138,
    "success_rate_percent": 42.5,
    "sample_status": "usable"
  },
  "calibration_report": {
    "version_label": "confidence-reliability-v1",
    "brier_score": 0.24,
    "expected_calibration_error": 0.08,
    "bins": []
  },
  "smoothed_calibration_report": {
    "version_label": "confidence-reliability-v2-smoothed",
    "brier_score": 0.23,
    "expected_calibration_error": 0.07,
    "bins": []
  },
  "cohorts": {
    "by_confidence_bucket": [],
    "by_setup_family": [],
    "by_horizon": [],
    "by_transmission_bias": [],
    "by_context_regime": [],
    "by_horizon_setup_family": []
  },
  "warnings": []
}
```

## Cohorts and slices

All calibration modes should support these slices where data is available:

- confidence bucket
- setup family
- action/direction
- horizon
- transmission bias
- context regime
- horizon + setup family
- ticker
- sector/industry when available
- fundamental valuation buckets when available:
  - mispricing signal
  - valuation bucket
  - fundamental directional support

Phantom-specific reports should additionally show:

- original action (`no_action`, `watchlist`, or filtered/discarded signal when available)
- intended action (`long`/`short`) when known
- shortlist state
- actionability rejection reason
- near-entry/missed-entry diagnostics when available

## Sample-status rules

Every report and cohort must include sample status.

Suggested statuses:

- `empty`: no included resolved samples
- `sparse`: fewer than 20 included samples
- `thin`: 20-49 included samples
- `usable`: 50-199 included samples
- `strong`: 200+ included samples

Autonomy and live confidence gating should require at least `usable` execution-only calibration, and preferably `strong`, depending on risk tier.

Phantom-only calibration can be used with `thin` status for diagnostics, but not for live broker confidence.

## Confidence-bin rules

Use stable bins for operator review:

- `<40`
- `40-50`
- `50-60`
- `60-70`
- `70-80`
- `80-90`
- `90+`

If the existing implementation uses different bins internally, the API may return both:

- `internal_bins`
- `operator_bins`

Do not hide sparse bins. Instead show sparse status and warnings.

## API requirements

Add or extend endpoints so operators can request calibration explicitly.

Recommended route:

```http
GET /api/calibration/confidence
```

Query parameters:

- `mode`: `execution_only | phantom_only | execution_plus_phantom | side_by_side`
- `window`: `7d | 14d | 30d | 90d | 180d | 365d | all`
- `evaluated_after`
- `evaluated_before`
- `computed_after`
- `computed_before`
- `ticker`
- `setup_family`
- `horizon`
- `action`
- `transmission_bias`
- `context_regime`
- `limit`

Existing calibration-report endpoints may remain, but they should either delegate to the same service or clearly document that they are execution-only legacy views.

## UI requirements

Research UI should provide a calibration workbench with:

- time-window selector
- mode selector:
  - execution only
  - phantom only
  - execution + phantom
  - side-by-side
- summary cards for sample count, success rate, Brier score, ECE, and sample status
- reliability chart by confidence bin
- cohort table
- warnings for sparse windows
- clear badge when phantom trades are included

Operator-facing copy must clearly distinguish:

- “execution confidence” from real/broker-preferred wins/losses
- “opportunity confidence” from phantom outcomes
- “mixed research view” from live/autonomy-safe confidence

## Calibration snapshot job target

There is currently no dedicated calibration job. Target behavior adds one.

Recommended job type:

```text
recommendation_calibration_refresh
```

Purpose:

- compute stable calibration snapshots on a schedule
- persist exact inputs, windows, modes, and results
- make autonomous gating auditable and reproducible
- avoid live behavior depending on transient read-time queries

Default schedule:

- daily after outcome-resolution jobs complete
- optional weekly full-history snapshot

Each job should produce and persist:

- execution-only report for `30d`, `90d`, `180d`, and `all`
- phantom-only report for `30d`, `90d`, `180d`, and `all`
- side-by-side summary
- sample sufficiency status
- warnings and recommended operator actions

Persisted snapshot fields:

- snapshot id
- created_at
- job_id/run_id
- mode
- window parameters
- included/excluded label policy
- source outcome counts by raw label
- calibration reports
- cohort summaries
- warnings
- code/schema version

Live watchlist calibration may continue computing read-time reports until snapshots exist. Once snapshots exist, live/autonomy logic should prefer the latest fresh execution-only snapshot and fall back to read-time computation only with a warning.

## Gating relationship

Signal gating jobs do not calibrate confidence because they solve a different problem.

Signal gating is for **upstream shortlist recall/selectivity**:

- should this ticker/signal reach deeper analysis?
- are thresholds too strict or too permissive?
- are near-misses being rejected incorrectly?
- are degraded inputs being over/under penalized?

Confidence calibration is for **probability honesty**:

- does 70% confidence actually behave like a 70% win probability?
- should confidence be adjusted downward/upward based on empirical reliability?
- is the calibration curve trustworthy enough for gating/autonomy?

The two workflows share evidence but should not be conflated.

Signal gating may use phantom labels because phantom labels are useful for recall/missed-opportunity analysis. Calibration may expose phantom-only or mixed reports, but live execution confidence must default to execution-only labels.

## Promotion and autonomy policy

Live/autonomous trading should use only execution-only calibration unless explicitly overridden by a future spec and validated evidence.

Before calibration affects autonomy:

- execution-only sample status must be at least `usable`
- Brier/ECE must be within configured safety limits
- recent and longer-window calibration must not strongly disagree
- cohort concentration must be acceptable
- phantom evidence may inform recall tuning but must not inflate broker execution confidence

If calibration is sparse or stale:

- show dashboard/operator warning
- keep confidence adjustments conservative
- avoid enabling more autonomy based on calibration

## Acceptance criteria

This feature is complete when:

1. Operators can request calibration for arbitrary supported time windows.
2. Operators can choose execution-only, phantom-only, mixed, or side-by-side calibration.
3. Reports clearly disclose included/excluded labels and binary mapping.
4. Phantom inclusion is never silent.
5. Execution-only remains the default for live confidence and autonomy.
6. Sparse windows return useful reports with clear warnings instead of misleading confidence.
7. The UI makes execution calibration and opportunity/phantom calibration visibly distinct.
8. A future scheduled job can persist calibration snapshots without changing report semantics.
