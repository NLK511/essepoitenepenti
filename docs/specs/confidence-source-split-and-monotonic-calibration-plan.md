# Confidence Source Split and Monotonic Calibration Plan

Status: planned after July 2026 raw-confidence backfill

## Problem

The new empirical calibration and conservative raw-confidence scorer made confidence more honest, but promotion is still blocked by:

- `calibration_bucket_gap_exceeds_limit`
- `calibration_non_monotonic_confidence_buckets`

After backfilling historical confidence, the latest execution-only calibration snapshot still shows:

- 0-40 bucket: 766 samples, actual WR 32.38%, avg confidence 32.91%
- 40-45 bucket: 276 samples, actual WR 32.61%, avg confidence 42.59%
- 45-50 bucket: 213 samples, actual WR 31.92%, avg confidence 47.38%
- 50-55 bucket: 179 samples, actual WR 36.87%, avg confidence 52.57%
- 55-60 bucket: 110 samples, actual WR 36.36%, avg confidence 57.16%
- 60-65 bucket: 32 samples, actual WR 31.25%, avg confidence 61.79%
- 65-70 bucket: 3 samples, actual WR 0.00%, avg confidence 65.74%

This is no longer just a stale-data issue. The remaining instability is structural:

- broker-resolved outcomes and simulation fallback outcomes are different label populations;
- setup families with different base rates are still being pushed through one global curve;
- upper confidence buckets are sample-thin;
- raw confidence is a useful rank score, but not yet monotonic enough to treat as a direct probability.

## Direction Change

Do not keep tuning thresholds against one blended confidence population.

The next architecture should treat confidence calibration as source-aware and monotonic:

```text
raw confidence components
  -> conservative raw confidence rank score
  -> source-aware calibration population
  -> monotonic calibrated win probability
  -> EV/actionability policy
```

Source-aware means:

- broker-only calibration for real executed trade reliability;
- simulation-only calibration for replay/phantom diagnostic reliability;
- blended calibration only for broad research summaries, not live actionability;
- explicit warnings when one source is being used as fallback for another.

## Implementation Plan

### 1. Add Outcome Source as a First-Class Calibration Dimension

Persist and expose a normalized label source on calibration observations:

- `broker`
- `simulation`
- `execution_plus_simulation`

Update:

- `EffectivePlanOutcomeRepository`
- `RecommendationPlanCalibrationService`
- `ConfidenceCalibrationObservation`
- `confidence_report`
- `calibration_health_report`
- calibration snapshot artifact schema

Acceptance criteria:

- every calibration report includes `label_source`;
- reports can be requested for broker-only and simulation-only populations;
- mixed reports explicitly identify themselves as mixed and are not eligible for live promotion.

### 2. Make Live Actionability Use Broker-First Calibration

For live plan framing and broker steering:

- prefer broker-only calibration when broker sample status is usable or strong;
- fall back to execution-plus-simulation only with an explicit degraded calibration status;
- never let simulation-only calibration promote live actionability;
- keep simulation-only calibration available for replay/tuning diagnostics.

Acceptance criteria:

- `WatchlistCalibrationReviewService` receives the intended calibration source;
- calibration review artifacts include `calibration_source`;
- promotion gates block live promotion when broker-only data is thin unless explicitly overridden.

### 3. Replace Free Empirical Buckets With Monotonic Calibration

Use monotonic pooling across confidence buckets so calibrated probability cannot go down as raw confidence rises.

Initial method:

- bucket by raw confidence using coarse bins while samples remain thin;
- compute empirical WR per bucket;
- apply isotonic regression / PAVA over ordered buckets;
- shrink each pooled bucket toward global/source prior based on sample count;
- output calibrated probability from the pooled monotonic curve.

Rules:

- 5-point buckets only when each active bucket has enough samples and dates;
- otherwise use coarser buckets: `<40`, `40-50`, `50-60`, `60+`;
- buckets with fewer than minimum samples should be pooled into neighbors before health checks.

Acceptance criteria:

- smoothed calibration report is monotonic by construction;
- raw bucket health can still warn about scorer instability;
- calibrated probability curve is stable enough for policy use.

### 4. Separate Rank Health From Probability Calibration Health

Keep two different diagnostics:

1. raw-rank health:
   - whether higher raw confidence generally wins more often;
   - used to judge the upstream confidence generator.

2. calibrated-probability health:
   - whether calibrated probabilities match observed outcomes;
   - used to judge probability reliability.

Current blockers conflate these. After monotonic calibration, non-monotonic raw buckets should not automatically block calibrated-probability use, but they should still block promotion of the raw scorer.

Acceptance criteria:

- calibration artifacts expose both health sections;
- promotion policy can distinguish `raw_rank_unstable` from `calibrated_probability_unstable`;
- actionability uses calibrated-probability health, not raw bucket monotonicity alone.

### 5. Add Segment Shrinkage Only After Source Split

Do not fit a separate model per setup family yet. Instead:

- compute global source-aware monotonic curve;
- compute setup-family and context-regime residuals;
- apply residual adjustments only when segment sample/date counts are usable;
- shrink residuals toward zero when thin.

Initial segment candidates:

- setup family;
- action long/short;
- context/transmission bias;
- horizon;
- broker vs simulation source.

Acceptance criteria:

- no segment can move calibrated confidence more than a bounded amount at first;
- thin segments produce warnings, not hard probability edits;
- segment effects are validated on holdout before promotion.

### 6. Backfill and Refresh Workflow

Any future raw confidence formula change must include:

1. dry-run historical confidence backfill;
2. source-aware calibration refresh;
3. before/after Brier and ECE by source;
4. raw-rank health by source;
5. promotion blocker comparison;
6. persisted artifact containing the exact formula version.

Acceptance criteria:

- backfill script remains dry-run by default;
- calibration snapshots include confidence formula version;
- large refreshes stay bounded/chunked.

## Promotion Rules

A calibration/scoring change may be promoted only when:

- broker-only sample is at least usable, or live mode is explicitly marked degraded;
- calibrated Brier does not worsen on holdout;
- calibrated ECE improves or remains within tolerance;
- monotonic calibrated curve passes health checks;
- no single date or ticker dominates the improvement;
- raw-rank instability is acknowledged and does not leak into probability claims.

## Stop Conditions

Stop trying to fix this with calibration alone if:

- broker-only raw-rank health remains badly non-monotonic after source split;
- live broker WR remains far below simulation WR after controlling for setup/action;
- the same setup family repeatedly scores high but loses on broker outcomes;
- confidence improvement is only visible in simulation fallback.

In that case, the next fix is upstream signal generation, not calibration.
