# Effective Plan Outcome Spec

**Status:** current behavior

## Problem
The app has several outcome records:

- `RecommendationOutcome`: simulated/replay/manual outcome evidence.
- `BrokerOrderExecution`: broker submission audit trail.
- `BrokerPosition`: broker-backed position lifecycle and realized P&L.

Before this spec, many services read only simulated recommendation outcomes and ignored broker-resolved wins/losses. That made confidence calibration, performance assessment, and research summaries disagree with broker reality.

## Canonical rule
For every recommendation plan, the app must expose one effective outcome. Source precedence is:

1. Closed broker position (`win` or `loss`).
2. Simulated/replay/manual recommendation outcome.
3. Open/review broker position (`submitted`, `open`, `needs_review`, `error`, `canceled`) as broker-backed unresolved state when no simulation exists.
4. Plan fallback unresolved state.

Closed broker positions override simulated outcomes. Any non-closed broker state should defer to simulation when simulation exists; broker-backed unresolved state is only used when no simulation record exists.

## Market outcome versus execution outcome
`win` and `loss` are market/trade outcomes. Risk-skipped, failed, rejected, and canceled broker orders are execution outcomes and must not be counted as market losses unless a broker position explicitly closed as a loss.

## Effective outcome fields
The canonical model reuses `RecommendationPlanOutcome` and adds source/realized fields:

- `outcome_source`: `broker`, `simulation`, or `plan`
- `outcome`: `win`, `loss`, `open`, `no_action`, `watchlist`, etc.
- `status`: `resolved`, `open`, or broker lifecycle state
- `evaluated_at`: broker exit timestamp, simulation evaluated timestamp, or plan computed timestamp
- recommendation metadata: ticker, action, confidence, horizon, setup family, transmission/context buckets
- broker realized metrics when available: P&L, return %, R multiple

## Required consumers
These systems must use effective outcomes when measuring recommendation quality:

- confidence calibration
- recommendation quality summaries
- performance assessment
- plan-generation tuning and walk-forward validation
- broad plan-generation search
- ticker/performance summaries where possible

## Current implementation
`EffectivePlanOutcomeRepository` builds effective outcomes by joining recommendation plans with broker positions and recommendation outcomes. `RecommendationPlanCalibrationService` accepts either the raw recommendation outcome repository or the effective outcome repository, but product analytics must pass the effective repository.

Operator-facing summaries should keep the distinction visible:
- dashboard headline win rate and profit should use the effective aggregate, with broker win rate / broker realized P&L shown as detail
- recommendation-plan analytics should show overall effective win rate, actionable win rate, and phantom win rate side by side
- raw simulated entry-miss and actionability diagnostics must be named with a `simulated_` prefix when they appear beside effective metrics

## API naming rules

- Effective/broker-preferred metrics may use headline names such as `win_rate_percent`, `total_profit`, or `policy_evaluation` only when the endpoint documentation makes the effective source clear.
- Simulation-only diagnostics must use explicit names such as `simulated_entry_miss_diagnostics` or `simulated_actionability_diagnostics`.
- Compatibility aliases may keep old keys temporarily, but the explicit `simulated_*` key must be present for new callers.
- Repository filtering must not apply a small pre-filtered plan limit before semantic filters such as outcome, resolved state, setup family, or evaluated window. The effective repository must fetch enough candidate plans, or push filters into SQL where practical, so narrow cohorts are not hidden behind newer unmatched plans.

`RecommendationOutcomeRepository` remains the raw simulated/replay/manual persistence adapter. New code must use explicit raw method names such as `list_simulated_outcomes` or `get_simulated_outcomes_by_plan_ids` when it deliberately needs simulation-only evidence.

The API exposes the canonical view at `/api/effective-plan-outcomes`. Existing `/api/recommendation-outcomes` analytics endpoints are kept as compatibility aliases for effective outcomes; raw simulation access should be added explicitly if needed rather than overloading those endpoints again.

When callers pass `evaluated_after` / `evaluated_before`, filtering and ordering are based on the effective outcome `evaluated_at` timestamp, not plan creation time. Broker-resolved rows use broker exit/update time, simulated rows use simulation `evaluated_at`, and plan fallbacks use plan `computed_at` only when no broker/simulation outcome exists.

## Regression expectations
Tests must cover:

- broker win overrides simulated loss
- broker loss overrides simulated win
- open broker position remains unresolved
- simulation fallback is used when no broker position exists
- confidence calibration counts broker-resolved outcomes
