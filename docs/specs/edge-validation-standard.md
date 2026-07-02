# Edge validation and autonomy gate standard

**Status:** current and target behavior

This standard defines the minimum evidence required before Trade Proposer App may expand autonomous broker execution.

It is intentionally conservative. A coherent plan, high confidence score, or good-looking backtest is not enough. Autonomy may expand only when broker-preferred outcomes show a repeatable edge that survives baseline, calibration, concentration, and drawdown checks.

## Current behavior

The gate is implemented through `EdgeValidationGateService` and operator trust is assembled through `PolicyTrustReport`. Plan-generation tuning auto-promotion is blocked unless the gate returns `eligible_for_cautious_expansion`.

## Target behavior

Any future setting that increases broker autonomy scope, exposure, frequency, or live mutation power must use this gate before it ships.

## Scope

This standard applies before any increase in:

- allowed broker order count
- allowed notional exposure
- allowed same-ticker exposure
- unattended run frequency
- automatic promotion of tuning configurations
- broader watchlist or setup-family autonomy

The standard does not block manual operator review or paper-only research, but it must block higher autonomy.

## Evidence source hierarchy

Use broker-preferred effective outcomes:

1. broker-position lifecycle outcomes when available
2. simulated recommendation outcomes only as secondary evidence
3. open or unresolved outcomes do not count as passed evidence

A policy must report the broker-backed share of selected resolved outcomes. Simulation-heavy evidence can support research, but it cannot justify higher autonomy by itself.

## Required gate inputs

The autonomy gate must evaluate:

- selected resolved outcome count
- broker-backed selected outcome count and share
- selected win rate
- realized P&L
- expected value or average return / R multiple
- profit factor when loss samples exist
- calibration gap and Brier/ECE where available
- baseline comparison against simple policies
- walk-forward / out-of-sample stability
- max drawdown and loss streak
- setup-family, action, ticker, and regime concentration
- degraded-input share
- broker-reconciliation certainty for the evidence used by the policy summary

Operator-facing consumers must not call the gate with silently omitted inputs. They must use a shared `PolicyTrustReport` assembly that either supplies each required input or records an explicit missing-input reason. Missing required inputs keep the autonomy label below `eligible_for_cautious_expansion`.

## PolicyTrustReport read model

`PolicyTrustReport` is the canonical operator and promotion read model for current policy trust. It contains:

- `edge_validation_gate`: the authoritative autonomy gate result.
- `policy_health_headline`: a compact derived headline for UI continuity. It is not an autonomy gate and must not contradict the edge gate.
- `policy_evaluation`: selected-outcome metrics from the active policy evaluator.
- `reliability_report`: bucketed reliability/calibration summary.
- `walk_forward_validation`: current walk-forward validation when available.
- `evidence_concentration`: current concentration summary when available.
- `degraded_input_summary`: degraded-input share and source when available.
- `broker_reconciliation_summary`: broker certainty state used by the gate.
- `baseline_comparison_summary`: selected-policy performance compared with a simple non-selected baseline.
- `drawdown_summary`: selected-policy max drawdown and breach state.
- `loss_streak_summary`: selected-policy recent/max loss-streak and breach state.
- `missing_inputs`: machine-readable list of required inputs that were not available.

Dashboard, recommendation-quality, research, and tuning promotion must use this read model instead of stitching trust labels independently.

## Minimum pass criteria

A policy may be considered for autonomy expansion only when all of these pass:

1. **Sample size**
   - at least 100 selected resolved outcomes, and
   - at least 50 broker-backed selected resolved outcomes, and
   - broker-backed selected outcome share at least 50%.

2. **Baseline advantage**
   - selected win rate is above the relevant simple baseline by at least 5 percentage points, or
   - selected average return / R multiple is materially better than baseline while win rate is not worse.

3. **Positive economics**
   - realized P&L is positive after known costs where costs are available, and
   - average selected return or average R multiple is positive, and
   - profit factor is at least 1.25 when there are enough realized losses to compute it.

4. **Calibration discipline**
   - absolute calibration gap is no more than 10 percentage points on the selected cohort, and
   - Brier/ECE are not worse than the current policy baseline.

5. **Walk-forward stability**
   - at least 3 qualified walk-forward slices, and
   - no recent qualified slice shows a severe regression, and
   - promotion is recommended by the walk-forward validation report.

6. **Drawdown and loss-streak control**
   - no unresolved drawdown breach exists, and
   - recent consecutive loss count is below the configured halt threshold, and
   - daily loss limits would not have been repeatedly breached by the selected policy.

7. **Concentration control**
   - no single ticker, setup family, direction, or market regime explains most of the edge unless that concentration is explicitly approved as a narrow policy.

8. **Input quality**
   - degraded-input rows do not dominate passed evidence, and
   - degraded-input performance is not materially worse than healthy-input performance.

## Failure labels

The gate should return machine-readable reasons, including:

- `thin_selected_sample`
- `thin_broker_sample`
- `simulation_heavy_evidence`
- `baseline_underperformance`
- `negative_realized_pnl`
- `weak_expected_value`
- `weak_profit_factor`
- `large_calibration_gap`
- `walk_forward_not_recommended`
- `recent_slice_regression`
- `drawdown_or_loss_streak_breach`
- `concentrated_edge`
- `degraded_input_edge`
- `broker_reconciliation_uncertain`
- `walk_forward_input_missing`
- `concentration_input_missing`
- `degraded_input_input_missing`
- `broker_reconciliation_input_missing`
- `baseline_comparison_input_missing`
- `baseline_underperformance`
- `drawdown_input_missing`
- `drawdown_or_loss_streak_breach`
- `loss_streak_input_missing`

## Operator stance labels

The gate should produce one of these labels:

- `blocked` — autonomy must not expand.
- `research_only` — useful for manual review or paper exploration, but not higher autonomy.
- `watch` — enough evidence for close operator monitoring, not enough for expansion.
- `eligible_for_cautious_expansion` — passes the standard and can be considered for small controlled expansion.
- `demote_or_halt` — live evidence deteriorated after prior eligibility.

## Expansion rule

Even when the gate passes, autonomy must expand in small increments only:

- increase one risk limit or scope dimension at a time
- require a fresh review window after each increase
- automatically demote or halt if live evidence falls below the standard

## Implementation conformance

Implemented contract:

- service-level gate using broker-preferred effective outcomes
- research/performance visibility
- UI rendering near `policy_health`
- plan-generation tuning promotion integration
- regression tests for pass, fail, demote, broker-uncertain, and tuning-promotion block cases

Manual promotion of a specific eligible candidate does not depend on this gate. There is no separate broker autonomy-scope expansion setting today.
