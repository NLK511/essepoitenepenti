# Plan Reliability Report Spec

## Status
Implemented in the first backend/read-model slice.

## Goal
Provide one canonical broker/effective outcome report for answering:

> Which confidence bands, actions, and setup families are actually reliable enough to influence trading policy?

The report exists because confidence, calibration, performance, and tuning code had drifted into overlapping local summaries. For autonomous trading, the app needs one broker-preferred reliability contract before tuning or gating can safely trust historical evidence.

## Source of truth
The report reads from `EffectivePlanOutcomeRepository`.

That means:
- broker-resolved positions are preferred when available
- simulated outcomes remain fallback/research evidence
- unresolved/open plans are included in total sample counts but not in win-rate, P&L, R-multiple, profit-factor, or calibration-gap metrics

## Canonical report slices
The initial report produces these slices:

- `confidence_bucket`
- `setup_family`
- `action`

Each slice contains ordered buckets. A bucket is a normalized cohort of effective outcomes.

## Bucket fields
Each bucket must expose:

- `slice_name`
- `key`
- `label`
- `total_count`
- `resolved_count`
- `win_count`
- `loss_count`
- `win_rate_percent`
- `average_confidence_percent`
- `calibration_gap_percent`
- `realized_pnl`
- `average_return_percent`
- `average_r_multiple`
- `profit_factor`
- `broker_outcome_count`
- `simulation_outcome_count`
- `plan_outcome_count`
- `sample_status`
- `min_required_resolved_count`

`calibration_gap_percent` is `average_confidence_percent - win_rate_percent`, in percentage points. Positive values mean overconfidence.

`profit_factor` is gross wins divided by absolute gross losses. It is `null` when the denominator is zero or when there is no resolved sample.

## Sample status
Sample status labels are intentionally simple:

- `strong`: at least twice the minimum resolved sample, or minimum plus 8
- `usable`: at least the minimum resolved sample
- `limited`: at least half the minimum resolved sample
- `insufficient`: smaller than limited

Minimum resolved sample defaults:

- confidence bucket: 10
- setup family: 10
- action: 10

## API/read model
`GET /api/research/performance-workbench` includes:

- `reliability_report`

Lower-level APIs remain available. The workbench report is the preferred Research page/read-model contract.

## Current implementation boundary
This slice creates the canonical report and exposes it in the Research workbench. It does not yet replace every tuning/scoring consumer.

Future migrations should move signal-gating review and plan-generation tuning scoring to this report, or to a narrower evaluator built from the same bucket calculations.
