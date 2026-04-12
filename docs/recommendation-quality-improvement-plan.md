# Recommendation quality improvement plan

**Status:** active tracking plan

This document is the working plan for improving recommendation quality, calibration, and reviewability in Trade Proposer App.

It is intentionally practical:
- track what we want to improve
- define how we will measure it
- record what changes we make
- keep the scope small enough to execute

## What success looks like

We want recommendations that are:
- more accurate than simple baselines
- better calibrated
- more stable across setup families and regimes
- honest about degraded inputs
- explainable to operators

## North-star metrics

Track these before and after each change:

1. **Actionable win rate**
   - long/short plans only
   - compare against simple baselines

2. **Expected value**
   - per resolved actionable plan
   - include a consistent cost assumption when available

3. **Calibration quality**
   - Brier score
   - expected calibration error
   - reliability by confidence bucket

4. **Coverage / selectivity**
   - how many candidates become actionable
   - how many are rejected or become `no_action`
   - shortlist rate and deep-analysis rate

5. **Degradation discipline**
   - how often degraded inputs still pass gates
   - performance of degraded vs healthy rows

6. **Slice stability**
   - setup family
   - horizon
   - transmission bias
   - context regime
   - shortlisted vs not shortlisted

## Implemented so far

- [x] added time-windowed outcome and plan filters for slice-based evaluation
- [x] added a smoothed calibration report alongside the current bucket-based report
- [x] added windowed performance-assessment snapshots for 30d / 90d / 180d views
- [x] added a walk-forward validation report and research-page validation tab
- [x] added plan-generation walk-forward promotion validation and a guarded promotion gate
- [x] added a consolidated recommendation-quality summary API and dashboard card
- [x] added a dedicated recommendation-quality research page and research-hub entry for the consolidated summary
- [x] added expected-value-style 5d return comparisons for actionable and high-confidence cohorts
- [x] added a calibration-strength scale to reduce over-correction in thin calibration reviews

## Workstreams

### A. Measurement and evaluation
Make sure we can trust the numbers.

Deliverables:
- a repeatable evaluation report
- baseline comparison tables
- time-sliced / walk-forward summaries
- slice-level breakdowns by family and regime

### B. Calibration
Make confidence more honest.

Deliverables:
- confidence-to-outcome reliability review
- per-family calibration analysis
- better bucket handling for thin data
- a clearer rule for how confidence is adjusted

### C. Scoring and gating
Improve the recommendation decision itself.

Deliverables:
- better shortlist thresholds
- better plan-generation thresholds
- clearer penalties for weak or degraded evidence
- fewer false positives without crushing recall

### D. Data quality and context quality
Improve the inputs before changing the gate too much.

Deliverables:
- better degraded-input detection
- better context freshness handling
- better evidence concentration checks
- better transmission/context regime labeling

### E. Validation and backtesting
Protect against tuning to noise.

Deliverables:
- walk-forward validation
- held-out recent period checks
- setup-family-specific comparison
- regression checks against simple baselines

### F. Operator surfaces
Make the work inspectable.

Deliverables:
- summary dashboards
- calibration report review
- baseline comparison view
- decision-sample filtering and triage support

## Current focus

The baseline snapshot, time-window filters, walk-forward validation, consolidated summary API, and operator summary pages are already shipped.

What remains is refinement rather than broad platform work:

- [ ] compare the current bucket-based calibration against a more statistical mapping
- [ ] test calibration separately for setup family and horizon when sample size is sufficient
- [ ] keep thin buckets visibly thin instead of smoothing them into strong-looking results
- [ ] document the confidence-to-outcome reliability curve before and after changes
- [ ] tune shortlist thresholds in `src/trade_proposer_app/services/watchlist_orchestration.py`
- [ ] tune plan-generation thresholds and penalty logic in the same orchestration path
- [ ] review whether degraded-input penalties should be stronger for specific conditions
- [ ] verify the impact on false positives, skipped wins, and overall selectivity
- [ ] run walk-forward comparisons over time slices instead of a single pooled split
- [ ] compare each candidate against simple baselines from `RecommendationPlanBaselineService`
- [ ] measure family/regime stability before promotion
- [ ] keep the latest-recent slice as a holdout check before accepting a change

## Metrics and data sources

### Primary sources

- `RecommendationPlanOutcome` for resolved results and horizon returns
- `RecommendationDecisionSample` for gating decisions and review priority
- `RecommendationPlan` for action, confidence, and plan-level context
- calibration and baseline services for the slice summaries

### Primary APIs to use

- `GET /api/recommendation-outcomes`
- `GET /api/recommendation-outcomes/summary`
- `GET /api/recommendation-outcomes/calibration-report`
- `GET /api/recommendation-outcomes/setup-family-review`
- `GET /api/recommendation-outcomes/evidence-concentration`
- `GET /api/recommendation-plans/baselines`
- `GET /api/recommendation-decision-samples`
- `GET /api/signal-gating-tuning`
- `GET /api/signal-gating-tuning/runs`
- `GET /api/plan-generation-tuning`
- `GET /api/plan-generation-tuning/runs`

## First experiment batch

Start with a small, repeatable experiment set:

1. **Current baseline snapshot**
   - use the latest resolved outcomes window
   - record actionable win rate, Brier score, ECE, and baseline comparison tables

2. **Family slice check**
   - compare breakout, continuation, mean reversion, catalyst follow-through, and macro beneficiary/loser
   - identify the weakest family and the least stable family

3. **Calibration probe**
   - compare the current confidence curve with a held-out recent slice
   - record whether a family-specific calibration would likely help

4. **Gating probe**
   - review near-miss and degraded samples with high review priority
   - test whether a small threshold adjustment improves precision without collapsing recall

5. **Holdout sanity check**
   - rerun the best candidate setting on a later slice
   - accept the change only if the later slice still looks directionally better

## Success criteria for the backlog

We should consider the effort successful when:
- the baseline snapshot is reproducible
- calibration improves or becomes more honest without hidden regressions
- one or more setup families improve without a major downgrade elsewhere
- walk-forward checks support the change
- operators can explain why a setting changed

## Execution phases

### Phase 1 — Baseline the current system
Goal: know where we stand now.

Tasks:
- [ ] capture current actionable win rate
- [ ] capture current Brier score / calibration error
- [ ] capture family-level and regime-level win rates
- [ ] capture degraded-row performance
- [ ] record the current baseline thresholds and tuning settings

Exit criteria:
- we can reproduce the same metrics on demand
- we have a baseline snapshot to compare future changes against

### Phase 2 — Improve measurement quality
Goal: trust the evaluation pipeline.

Tasks:
- [ ] verify outcome filters and slice filters
- [ ] confirm baseline comparisons are correct
- [ ] add time-based evaluation slices if missing
- [ ] make thin buckets visibly thin instead of overstated

Exit criteria:
- evaluation output is stable and interpretable
- operators can tell when a slice is underpowered

### Phase 3 — Tighten calibration
Goal: confidence numbers mean more.

Tasks:
- [ ] compare current bucket calibration with a more statistical calibration method
- [ ] evaluate family-specific calibration behavior
- [ ] decide whether to keep, merge, or change bucket rules for thin buckets
- [ ] record calibration before/after on the same sample set

Exit criteria:
- lower calibration error without hurting actionable quality too much
- better alignment between confidence and realized win rate

### Phase 4 — Improve gating and scoring
Goal: better recommendations, not just prettier scores.

Tasks:
- [ ] tune shortlist thresholds against held-out data
- [ ] tune plan-generation thresholds against held-out data
- [ ] review penalties for degraded and contradictory evidence
- [ ] check whether any setup family deserves a separate gate

Exit criteria:
- actionable win rate improves or stays stable while false positives fall
- no major family/regime regression is introduced

### Phase 5 — Validate and lock in gains
Goal: avoid regressions.

Tasks:
- [ ] run walk-forward checks on the best candidate settings
- [ ] compare against simple baselines again
- [ ] verify degraded cases still stay visible and penalized
- [ ] document the final recommended settings and rationale

Exit criteria:
- improvements hold on later data slices
- the resulting settings are explainable and repeatable

## Decision log

Use this section to record important choices.

| Date | Decision | Why | Impact |
| --- | --- | --- | --- |
| 2026-04-11 | Added a dedicated recommendation-quality page and surfaced it from research navigation. | Make the consolidated calibration / baseline / walk-forward snapshot easier to inspect during tuning review. | Operators can reach the summary from dashboard, nav, and research hub. |

## Experiment log

Use this section to record tests and tuning runs.

| Date | Area | Change | Result | Keep / Revert |
| --- | --- | --- | --- | --- |
| 2026-04-11 | Operator surfaces | Added `/recommendation-quality` and linked it from the research hub. | Consolidated quality snapshot is easier to find without leaving the app workflow. | Keep |

## Risks to watch

- overfitting to the last sample set
- making confidence look better without improving outcomes
- improving one setup family while hurting another
- hiding degraded inputs behind smoother scores
- changing gates without a time-based validation check

## Recommended review cadence

- **weekly:** review metrics and tuning experiments
- **per change:** record the decision and the result
- **monthly:** compare against baselines and check drift by family/regime

## Suggested first three tasks

1. capture the current baseline metrics
2. identify the worst-performing setup families/regimes
3. choose one calibration improvement and one gating improvement to test next

## Related docs

- `recommendation-methodology.md`
- `decision-sample-tuning-guide.md`
- `signal-gating-tuning-guide.md`
- `plan-generation-tuning-spec.md`
- `archive/implementation-plans/historical-replay-backtesting-plan.md`
- `recommendation-plan-resolution-spec.md`
