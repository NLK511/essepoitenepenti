# Plan Policy Evaluator Spec

## Status
Implemented in the first additive slice.

## Goal
Provide one canonical evaluator for answering:

> If this trade-selection policy had selected historical plans, how did those selected plans perform using broker-preferred outcomes?

This reconciles drift between plan-generation tuning, signal-gating tuning, calibration, quality summary, and trade policy. Those systems can still optimize different knobs, but they should not invent separate scoring semantics for selected historical plans.

## Source of truth
The evaluator reads from `EffectivePlanOutcomeRepository`.

That means:
- broker-resolved positions are preferred when available
- simulated outcomes are fallback/research evidence
- unresolved plans can be counted as selected context but do not affect win rate, P&L, R multiple, profit factor, or calibration penalty

## Policy input
The evaluator accepts a `TradeDecisionPolicy`.

A historical effective outcome is selected by the policy when:
- its action is allowed by the policy
- its setup family is allowed by the policy
- its confidence is at least the policy effective confidence threshold

The effective confidence threshold is `TradeDecisionPolicy.effective_confidence_threshold()`.

## Score fields
The evaluator returns `PlanPolicyEvaluation` with:

- `policy_id`
- `total_outcomes`
- `selected_outcomes`
- `resolved_selected_outcomes`
- `broker_selected_outcomes`
- `simulation_selected_outcomes`
- `win_count`
- `loss_count`
- `win_rate_percent`
- `average_confidence_percent`
- `calibration_gap_percent`
- `realized_pnl`
- `average_return_percent`
- `average_r_multiple`
- `profit_factor`
- `calibration_penalty`
- `robustness_label`
- `selection_rate_percent`

`calibration_gap_percent` is `average_confidence_percent - win_rate_percent`. Positive means overconfidence.

`calibration_penalty` is the absolute calibration gap expressed as a percentage-point value. It is `null` when either confidence or win rate is unavailable.

`profit_factor` is gross wins divided by absolute gross losses. It is `null` when there is no resolved selected sample or no realized loss denominator.

## Robustness labels
The first slice uses intentionally simple labels:

- `insufficient`: fewer than 10 resolved selected outcomes
- `limited`: at least 10 but fewer than 20 resolved selected outcomes
- `usable`: at least 20 resolved selected outcomes
- `strong`: at least 40 resolved selected outcomes and a non-negative realized P&L

These labels are conservative and should gate autonomous promotion in future migrations.

## Initial consumer
`RecommendationQualitySummaryService` includes an active-policy evaluation in the quality summary payload. This is a low-risk read-only migration; it does not change trading decisions or tuning promotion behavior.

## Future migrations
Future batches should migrate:
- plan-generation tuning candidate scoring
- signal-gating tuning candidate scoring
- Research/quality policy comparison views

to use this evaluator or narrower evaluators built from the same selected-outcome scoring semantics.
