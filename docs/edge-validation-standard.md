# Edge validation and autonomy gate standard

**Status:** target behavior

This standard defines the minimum evidence required before Aurelio may expand autonomous broker execution.

It is intentionally conservative. A coherent plan, high confidence score, or good-looking backtest is not enough. Autonomy may expand only when broker-preferred outcomes show a repeatable edge that survives baseline, calibration, concentration, and drawdown checks.

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

## Required implementation path

1. [x] Implement the standard as a service using broker-preferred effective outcomes.
2. [x] Expose the result in the research/performance workbench.
3. [x] Render the result near `policy_health` in the UI.
4. [ ] Wire the result into tuning promotion and broker autonomy settings.
5. [x] Add regression tests for pass, fail, demote, and broker-uncertain cases.

## Current conformance

Current behavior computes and displays the gate through `EdgeValidationGateService`, the research performance workbench, and the Research UI. Autonomy expansion is not yet fully bound to this gate in tuning promotion and broker autonomy settings.
