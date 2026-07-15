# Confidence calibration spec

**Status:** current behavior

This spec defines how Trade Proposer App computes and inspects confidence calibration across time windows, including operator-controlled inclusion or exclusion of phantom trades. Live plan generation uses the latest persisted execution-only calibration snapshot rather than recomputing calibration on every plan-generation run.

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
- A weekly scheduled calibration refresh job persists its snapshot in the run artifact. A dedicated calibration snapshot table remains future work.

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

Large live calibration refreshes must read effective outcomes in bounded batches. They must not build a single broker/simulation lookup over tens of thousands of plan IDs, because that can stall the refresh worker and leave the persisted snapshot stale.

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

A dedicated calibration refresh job runs weekly during the weekend.

Job type:

```text
recommendation_calibration_refresh
```

Purpose:

- compute stable calibration snapshots on a schedule
- persist exact inputs, windows, modes, and results
- make autonomous gating auditable and reproducible
- avoid live behavior depending on transient read-time queries

Default schedule:

- weekly on Saturday at 06:30 UTC, after the Saturday gating severity check and before the heavier weekend fundamental-analysis batches
- optional future weekly/full-history variants may be added if snapshot volume grows

Each job produces and persists:

- live execution-only calibration summary for all available execution outcomes
- execution-only confidence report for `all`
- phantom-only confidence report for `all`
- execution + phantom confidence report for `all`
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

Live watchlist calibration must use the latest completed weekly execution-only calibration snapshot. It must not recompute calibration during every plan-generation run. Phantom-inclusive modes remain research/operator views only and must not become the live calibration source without a later validated spec change. If no completed snapshot exists, live calibration should be unavailable/disabled rather than silently recomputed during proposal generation.

## Gating relationship

Signal gating jobs do not calibrate confidence because they solve a different problem.

Signal gating is for **upstream shortlist recall/selectivity**:

- should this ticker/signal reach deeper analysis?
- are thresholds too strict or too permissive?
- are near-misses being rejected incorrectly?
- are degraded inputs being over/under penalized?

Confidence calibration is for **probability honesty**. It is distinct from actionability-floor calibration, which searches the downstream threshold that converts already-framed intended actions into actionable recommendations.

Confidence calibration asks:
- when the app says confidence is X%, is the observed execution win rate consistent with X%?
- should live plan framing adjust calibrated confidence up/down because historical reliability is miscalibrated?

Actionability-floor calibration asks:
- given replay-generated plans and outcomes, which downstream actionable confidence floor in a bounded search range produced the best recent EV/actionability trade-off?

The two jobs must not be merged: confidence calibration changes confidence honesty/adjustment semantics, while actionability-floor calibration proposes one threshold parameter and reuses replay outcomes.

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

## 2026-07-14 confidence architecture redesign plan

**Status:** required redesign, not yet implemented.

July 2026 tuning diagnostics showed that the current architecture makes one bad assumption too easy:

> calibrated confidence is stable enough to tune actionability thresholds against directly.

That assumption is no longer acceptable. The current evidence shows confidence can be non-monotonic by window and can disagree sharply across recent selection and holdout slices. Threshold tuning on top of a drifting probability estimate produces misleading "best" candidates, because the search is optimizing a policy cutoff against a number whose meaning is not stable.

### Evidence that triggered the redesign

The diagnostic artifact `artifacts/confidence-bucket-calibration-diagnostic-20260714.json` compared stated confidence with realized win rate while disabling the confidence gate and keeping active trade geometry.

Global selection window (`2026-06-08` through `2026-06-17`):

- `0-40` bucket: average confidence `30.80%`, actual WR `38.60%`, gap `+7.80`.
- `40-45` bucket: average confidence `42.30%`, actual WR `39.58%`, gap `-2.72`.
- `45-50` bucket: average confidence `46.81%`, actual WR `45.83%`, gap `-0.98`.
- `50-55` bucket: average confidence `51.95%`, actual WR `63.64%`, gap `+11.69`, but thin sample.

Global holdout window (`2026-06-18` through `2026-07-10`):

- `0-40` bucket: average confidence `28.64%`, actual WR `45.94%`, gap `+17.30`.
- `40-45` bucket: average confidence `42.23%`, actual WR `26.23%`, gap `-16.01`.
- `45-50` bucket: average confidence `48.60%`, actual WR `31.25%`, gap `-17.35`.
- `50-55` bucket: average confidence `51.82%`, actual WR `28.89%`, gap `-22.93`.
- `55-60` bucket: average confidence `57.18%`, actual WR `8.33%`, gap `-48.85`, but thin sample.

This is not promotion-grade calibration evidence by itself, because several recent buckets are thin or date-concentrated. It is strong enough to require architectural change: confidence can no longer be treated as a clean, monotonic probability during tuning unless a calibration health check proves it.

### Terminology reset

The app must keep these concepts separate.

- **Raw signal score:** upstream model or rules score before reliability correction. It may be useful for ranking but is not necessarily a probability.
- **Calibrated confidence:** empirical estimate of win probability after reliability calibration. This is the only number that may be presented as probability-like confidence.
- **Actionability threshold:** policy cutoff deciding whether a plan is tradeable at the current confidence, risk, and operator policy.
- **Expected value:** payoff-aware outcome estimate. It must remain separate from win probability because a lower-WR plan can be better when reward/risk is favorable.
- **Actionability adjustment:** a threshold or policy adjustment for a setup/regime. It must not silently mutate calibrated confidence.

Bad past choice to retire:

- using a single confidence number as both probability estimate and trade eligibility score;
- interpreting threshold improvements as proof that confidence itself is stronger;
- searching actionability floors without first reporting whether confidence buckets are calibrated and monotonic.

### Target architecture

The plan-generation and tuning stack should become:

```text
raw plan features and raw confidence
  -> confidence calibration layer
  -> calibrated win probability
  -> EV/risk model
  -> actionability policy threshold
  -> trade/no-trade decision
```

Each layer has its own artifact fields, diagnostics, and promotion gates. A tuning run may not hide calibration instability behind a better actionability threshold.

### Phase 1 - calibration data contract

Add a reusable calibration dataset builder that creates frozen rows with:

- plan id and computed timestamp;
- ticker, setup family, action/direction, context bias/regime, horizon;
- raw confidence before calibration when available;
- currently persisted calibrated confidence;
- actionability reason and rejection reason;
- entry, stop, take-profit, risk percentage, reward percentage;
- resolved binary label for the requested mode;
- resolution source and data-quality status;
- evidence date and source hash when available.

Rules:

- Include only resolved labels for the chosen mode.
- Exclude open, expired-without-resolution, unresolved, and ambiguous rows from probability calibration.
- Disclose execution-only, phantom-only, and mixed label policies.
- Store enough identifiers to reproduce every calibration run.

Acceptance:

- The same input rows can feed calibration reports, tuning diagnostics, and replay audits.
- A calibration report can say exactly which rows were excluded and why.

### Phase 2 - mandatory pre-tuning calibration diagnostics

Every large-search, actionability-floor, or plan-generation tuning workflow must attach a calibration health section before candidate ranking.

Required diagnostics:

- reliability by stable confidence bucket;
- average stated confidence vs actual WR;
- calibration gap by bucket;
- sample status by bucket;
- distinct date count by bucket;
- ticker concentration by bucket;
- setup-family and context-bias slices;
- recent-selection and locked-holdout comparison;
- monotonicity warning when higher-confidence buckets do not outperform lower-confidence buckets.

Required artifact flags:

- `calibration_health_status`: `usable | thin | unstable | non_monotonic | stale | unavailable`;
- `calibration_blocks_promotion`: boolean;
- `calibration_blockers`: list of explicit reasons.

Acceptance:

- A tuning artifact cannot report a promotion candidate without also reporting calibration health.
- Non-monotonic recent confidence buckets block promotion unless the operator explicitly runs a research-only workflow.

### Phase 3 - simple global calibrator

Implement a boring global calibrator before any flexible segment model.

Candidate methods:

- reliability-bin smoothing for the current behavior;
- Platt/logistic calibration using raw confidence as the primary input;
- isotonic calibration only when sample size is strong enough, because it can overfit thin buckets.

Training protocol:

- train on older discovery history;
- select/check on walk-forward selection dates;
- test once on locked holdout;
- never fit and validate on the same recent window;
- persist model version, input hash, train window, selection window, holdout window, and metrics.

Promotion gates:

- expected calibration error improves;
- Brier score or log loss improves;
- monotonicity does not degrade;
- no bucket with `usable` sample status has an extreme unexplained gap;
- holdout metrics do not collapse relative to selection.

Acceptance:

- Live plan framing can load a persisted calibration model/snapshot.
- If the latest calibration is stale, sparse, or blocked, live framing falls back conservatively and reports calibration unavailable instead of silently pretending confidence is calibrated.

### Phase 4 - hierarchical segment calibration

Add segment calibration only after global calibration is stable.

Allowed hierarchy:

1. global calibration;
2. setup-family adjustment;
3. setup-family plus context-bias adjustment;
4. optional ticker/liquidity diagnostics only.

Rules:

- Segment adjustments must shrink toward the parent/global calibration.
- A segment cannot get a live adjustment unless it has enough resolved samples and enough distinct dates.
- Ticker-level adjustments are research-only unless future evidence is much larger.
- Segment adjustments must be represented as calibration adjustments only when they improve probability accuracy; otherwise they belong in actionability policy.

Acceptance:

- A `catalyst_follow_through + tailwind` adjustment cannot be promoted merely because it improves EV on one holdout date.
- Segment calibration must pass remove-best-date and concentration checks before affecting live confidence.

### Phase 5 - actionability policy after calibration

Actionability tuning must consume calibrated confidence and calibration health.

Policy rules:

- If calibration is blocked, promotion-oriented actionability tuning is blocked.
- Research tuning may still run, but artifacts must state that confidence is unstable.
- Segment-specific threshold deltas are policy controls, not confidence mutations.
- The UI/reporting must show:
  - raw confidence;
  - calibrated confidence;
  - global actionability floor;
  - segment policy delta, if any;
  - effective actionability threshold;
  - EV/risk decision.

Acceptance:

- A plan can honestly say: "calibrated win probability is 44%, but EV is positive enough to trade under policy."
- The system no longer needs to fake a higher confidence just to justify a lower actionability threshold.

### Phase 6 - operator and autonomy controls

Operator-facing reports must clearly distinguish:

- probability calibration status;
- actionability policy status;
- EV/risk status;
- promotion eligibility.

Autonomy gate:

- No calibration snapshot, stale snapshot, non-monotonic snapshot, or thin snapshot means no increase in autonomous scope.
- Existing narrow automation can continue if it does not depend on new confidence inflation.
- Any confidence-changing promotion requires explicit artifact-backed evidence and operator approval.

### Implementation order

1. Add calibration-health diagnostics to large-search and actionability-floor artifacts.
2. Create a standalone walk-forward confidence calibration job using the shared calibration dataset builder.
3. Persist calibration snapshots with train/selection/holdout metadata and model/schema version.
4. Make plan-generation tuning consume calibration health and block promotion when unstable.
5. Add global calibration model support in live plan framing, disabled by default until validated.
6. Add hierarchical setup-family/context-bias calibration only after global calibration proves useful.
7. Add actionability threshold deltas as a separate policy surface, not as confidence mutation.

### Stop conditions

Stop trying to fix this with threshold tuning when:

- confidence buckets remain non-monotonic after data-quality cleanup;
- calibrated confidence does not improve holdout Brier/ECE;
- segment adjustments only work by date concentration;
- EV improvements vanish after removing the best date;
- the replay evidence cannot produce enough resolved samples for calibration.

If those happen, the bottleneck is upstream plan/signal quality, not calibration or actionability policy.

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
9. Tuning workflows report calibration health before candidate ranking.
10. Promotion-oriented tuning is blocked when calibration is stale, thin, non-monotonic, or otherwise unstable.
11. Raw confidence, calibrated confidence, EV, and actionability threshold are represented as separate concepts in artifacts and operator-facing reports.
