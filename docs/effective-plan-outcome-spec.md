# Effective Plan Outcome Spec

## Status
Implemented in progress. The canonical effective outcome layer is the source of truth for performance, calibration, tuning, and research code that needs to ask whether a recommendation plan worked.

## Problem
The app has several outcome records:

- `RecommendationOutcome`: simulated/replay/manual outcome evidence.
- `BrokerOrderExecution`: broker submission audit trail.
- `BrokerPosition`: broker-backed position lifecycle and realized P&L.

Before this spec, many services read only simulated recommendation outcomes and ignored broker-resolved wins/losses. That made confidence calibration, performance assessment, and research summaries disagree with broker reality.

## Canonical rule
For every recommendation plan, the app must expose one effective outcome. Source precedence is:

1. Closed broker position (`win` or `loss`).
2. Open/review broker position (`submitted`, `open`, `needs_review`, `error`, `canceled`) as broker-backed unresolved state.
3. Simulated/replay/manual recommendation outcome.
4. Plan fallback unresolved state.

Closed broker positions override simulated outcomes. Simulation remains useful fallback evidence when no broker lifecycle record exists.

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
`EffectivePlanOutcomeRepository` builds effective outcomes by joining recommendation plans with broker positions and recommendation outcomes. `RecommendationPlanCalibrationService` now accepts either the legacy recommendation outcome repository or the effective outcome repository, so callers can migrate without changing calibration math.

## Regression expectations
Tests must cover:

- broker win overrides simulated loss
- broker loss overrides simulated win
- open broker position remains unresolved
- simulation fallback is used when no broker position exists
- confidence calibration counts broker-resolved outcomes
