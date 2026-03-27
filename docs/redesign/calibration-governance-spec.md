# Calibration Governance Spec

## Purpose

This document defines how outcome history should and should not influence recommendation-plan confidence and action gating.

The goal is to make calibration:
- conservative
- sample-aware
- operator-visible
- useful for decision support
- resistant to false precision

This spec does not treat current calibration as a statistical proof layer. It defines governance rules for using measured outcomes honestly.

## Scope

This applies to:
- `RecommendationPlanOutcome`
- calibration summaries
- calibration-aware action thresholds
- operator UI calibration views
- recommendation-plan review workflows

## Core rule

Calibration must never hide sparse evidence behind precise-looking threshold changes.

If the data is weak, the system should say so and reduce its reliance on narrow slices.

## Approved calibration slices

Calibration may be reviewed by:
- confidence bucket
- setup family
- horizon
- transmission bias
- context regime
- horizon + setup family

Future slices are allowed only if they can be shown to have enough data to be useful.

## Decision hierarchy

When applying calibration to action gating, the engine should use this hierarchy:
1. overall population
2. horizon
3. setup family
4. confidence bucket
5. transmission bias
6. context regime
7. horizon + setup family

Narrower slices should not dominate broader cohorts unless the sample size is clearly adequate.

## Minimum sample policy

Suggested minimum resolved counts before a slice can influence gating:
- overall: informational only
- horizon: 12
- setup family: 10
- confidence bucket: 10
- transmission bias: 10
- context regime: 10
- horizon + setup family: 8

Below those thresholds, the slice should remain visible in UI but should be marked:
- `insufficient_data`
- and should contribute either no threshold change or only a very small capped adjustment

## Sparse-slice handling

If a slice is below threshold:
- do not apply hard penalties or rewards
- display the slice count clearly
- prefer broader parent cohorts
- mark the calibration review as low-confidence

Suggested operator fields:
- `sample_status`: `insufficient | limited | usable | strong`
- `min_required_resolved_count`
- `resolved_count`

## Adjustment policy

Threshold changes must be bounded.

Suggested caps:
- per broad slice (`horizon`, `setup_family`, `confidence_bucket`): moderate cap
- per narrow slice (`transmission_bias`, `context_regime`, `horizon_setup_family`): smaller cap unless sample size is strong
- total upward adjustment cap: 15 points
- total downward adjustment cap: 6 points

The redesign should remain more willing to block weak plans than to relax standards aggressively.

## Recency policy

Calibration should eventually compare:
- recent window
- longer window

Suggested windows:
- recent: last 30 resolved trade plans
- medium: last 100 resolved trade plans
- full retained history: operator review only

If recent performance sharply diverges from longer history:
- display the divergence
- prefer caution
- avoid strong rewards based only on old history

## Shrinkage policy

Narrow slices should be shrunk toward broader cohorts.

Conceptually:
- `horizon + setup_family` should lean toward both `horizon` and `setup_family`
- `transmission_bias` should lean toward `overall`
- `context_regime` should lean toward `overall` and `horizon`

Even if the initial implementation stays heuristic, the docs should lock the policy intent:
- narrower slices should not move thresholds as if they were standalone truth

## Allowed uses of calibration

Calibration may be used to:
- raise action thresholds for underperforming cohorts
- modestly relax thresholds for clearly stronger cohorts
- flag plans for extra operator review
- explain when a plan was blocked despite decent raw confidence
- compare cohorts in operator workflows

## Disallowed uses of calibration

Calibration must not yet be used to:
- auto-size positions
- claim reliable probability estimates
- bypass explicit signal conflicts
- overrule broken trade structure
- treat small-sample slices as statistically meaningful

## Confidence interpretation policy

Confidence should still be understood as a structured heuristic confidence, not a proven probability.

Calibration should improve discipline around action gating, but should not be described as converting confidence into a trustworthy probability of success unless the data really supports that claim.

## Operator visibility requirements

Any calibration-driven threshold change should show:
- base threshold
- effective threshold
- threshold adjustment
- contributing slices
- resolved count for each slice
- win rate for each slice
- why the slice was considered usable or insufficient

If a plan is blocked due to calibration, the operator should be able to tell whether the main reason was:
- setup-family weakness
- horizon weakness
- poor transmission cohort behavior
- weak confidence bucket behavior
- mixed signals across multiple slices

## Review statuses

Every calibration review should include one of:
- `disabled`
- `insufficient_data`
- `heuristic_limited`
- `usable_for_gating`
- `strong_for_gating`

Suggested interpretation:
- `disabled`: no calibration summary available
- `insufficient_data`: too little evidence for meaningful gating influence
- `heuristic_limited`: some evidence, but thresholding should remain conservative
- `usable_for_gating`: enough evidence for bounded threshold changes
- `strong_for_gating`: unusually well-supported cohort behavior; still operator-visible

## Success criteria

Calibration governance is working if:
- threshold changes become easier to explain
- sparse cohorts stop causing noisy threshold movement
- blocked plans are easier to audit
- operators can see where the system is weak, not just where it is confident
- calibrated confidence is shown as a bounded adjustment from raw confidence rather than a fake precise probability
- evidence concentration surfaces help operators focus attention on the strongest usable cohorts instead of broadening usage blindly
- measured plan quality improves without pretending to have stronger certainty than the data supports
