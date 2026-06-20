# Recommendation quality and edge-validation backlog

**Status:** active plan

This is the remaining active backlog for improving recommendation quality, calibration, and reviewability.

The broad quality platform is already in place. This document now focuses on unresolved evidence questions and promotion discipline rather than re-listing shipped infrastructure.

## Current shipped baseline

Implemented quality infrastructure includes:

- broker-preferred effective outcomes for execution-aware truth
- outcome summaries, setup-family reviews, evidence-concentration reviews, and baseline comparisons
- decision samples for actionable, near-miss, degraded, and rejected cases
- walk-forward validation for plan-generation tuning
- guarded promotion checks for plan-generation thresholds
- large-search evaluation artifacts and rejection of unsafe candidates
- EV-expansion lane separated from precision/win-rate promotion
- configurable calibration reports for execution-only, phantom-only, combined, and side-by-side modes
- weekly persisted execution-only calibration snapshots for live plan generation
- calibration-aware confidence/actionability in the orchestration path when a snapshot exists
- dashboard/research surfaces for recommendation quality review

## Current stance

Confidence remains a ranking and selection signal unless calibrated evidence supports stronger interpretation.

Live/autonomous confidence calibration uses execution-only outcomes by default. Phantom outcomes are research/operator context and must not silently affect live execution confidence.

Do not reuse plan-outcome calibration for cheap-scan confidence. Cheap scan is an upstream recall mechanism and needs its own calibration design if it becomes calibrated later.

Do not promote large-search winners or new context features solely because they improve pooled expected value. Promotion needs walk-forward, slice stability, drawdown/loss-streak review, and baseline comparison.

## North-star metrics

Track before and after each quality change:

1. **Actionable win rate** — long/short plans only, compared with simple baselines.
2. **Expected value** — per resolved actionable plan with consistent cost/friction assumptions where available.
3. **Calibration quality** — Brier score, expected calibration error, and reliability by confidence bucket.
4. **Coverage/selectivity** — candidate, shortlist, deep-analysis, actionable, and no-action rates.
5. **Degradation discipline** — degraded vs healthy row performance and degraded rows that still pass gates.
6. **Slice stability** — setup family, horizon, transmission/ontology condition, context regime, market regime, and confidence bucket.

## Remaining active backlog

### 1. Validate current calibration behavior over time

Tasks:

- review weekly execution-only calibration snapshots after enough new outcomes accumulate
- compare raw vs calibrated confidence by bucket and horizon
- keep thin buckets visibly thin
- detect whether calibration improves Brier/ECE without hurting selection quality
- preserve side-by-side phantom reporting for research only

Promotion rule:

- calibration remains live only through persisted scheduled snapshots; no silent per-run recalculation fallback

### 2. Validate ontology and transmission usefulness

Tasks:

- run fresh ontology-enabled plan generation
- measure ontology context presence and matched exposure rate
- compare outcomes for tailwind/headwind/mixed/neutral transmission states
- compare curated vs template-generated ontology profiles
- measure whether ontology reduces mixed-bias or false-positive rates

Promotion rule:

- ontology may become stronger in gating/confidence only after walk-forward evidence shows benefit over taxonomy-only/transmission baseline

### 3. Validate fundamental valuation context passively

Tasks:

- backfill/evaluate enough point-in-time fundamental valuation contexts
- compare valuation, quality, growth, balance-sheet, and event-regime slices
- measure false-positive reduction, EV, drawdown/loss-streak behavior, and no-entry behavior
- keep sparse provider payloads visibly degraded

Promotion rule:

- no positive fundamental confidence boost until point-in-time walk-forward evidence beats baseline without worsening drawdown/loss streaks
- conservative caps or threshold raises require a separate explicit policy decision

### 4. Continue tuning with promotion discipline

Tasks:

- use walk-forward comparisons rather than pooled-only winners
- compare candidates against baseline and current production settings
- review actionability expansion, not just EV
- inspect false positives, skipped wins, and selectivity before accepting a change
- keep EV-expansion candidates separate from precision promotion

Promotion rule:

- reject candidates that improve EV only by greatly expanding actionability or materially worsening win rate unless explicitly treated as experimental and capped

### 5. Keep degraded-input penalties honest

Tasks:

- review degraded plans that pass gates
- identify specific degraded conditions that deserve stronger penalties
- distinguish missing required evidence from missing optional evidence
- ensure warnings are visible in operator surfaces and persisted payloads

Promotion rule:

- degraded-input changes should be measured by false-positive reduction and lost true-positive cost, not just fewer actions

### 6. Decide cheap-scan calibration separately

Tasks:

- define a cheap-scan outcome dataset that includes non-shortlisted decision samples
- include missed-opportunity benchmarks and clean rejects
- avoid training only on shortlisted or plan-generated rows

Promotion rule:

- do not apply recommendation-plan calibration directly to cheap-scan scores

## Data sources and APIs

Primary data:

- `RecommendationPlanOutcome`
- broker-preferred effective outcomes
- `RecommendationDecisionSample`
- `RecommendationPlan`
- calibration snapshots and reports
- baseline services
- plan-generation tuning runs and artifacts

Primary APIs:

- `GET /api/recommendation-outcomes`
- `GET /api/recommendation-outcomes/summary`
- `GET /api/recommendation-outcomes/calibration-report`
- `GET /api/recommendation-outcomes/setup-family-review`
- `GET /api/recommendation-outcomes/evidence-concentration`
- `GET /api/recommendation-plans/baselines`
- `GET /api/recommendation-decision-samples`
- `GET /api/calibration/confidence`
- `GET /api/signal-gating-tuning`
- `GET /api/plan-generation-tuning`

## Success criteria

Quality work is successful when:

- calibration is more honest without hidden regressions
- one or more cohorts improve without major degradation elsewhere
- walk-forward checks support the change
- simple baselines are not ignored
- degraded inputs are visible and penalized appropriately
- operators can explain why a threshold, cap, calibration curve, or context policy changed

## See also

- `recommendation-methodology.md`
- `specs/confidence-calibration-spec.md`
- `specs/edge-validation-standard.md`
- `specs/plan-generation-tuning-spec.md`
- `specs/large-parameter-search-spec.md`
- `specs/ticker-exposure-ontology-spec.md`
- `specs/fundamental-valuation-integration-spec.md`
