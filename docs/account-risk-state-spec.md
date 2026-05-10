# Account Risk State Spec

**Status:** current behavior

## Goal
Provide one canonical account-risk read model for answering:

> Is the account currently allowed to take a new trade, and why?

This separates the account-level safety question from strategy-selection policy and execution details.

## Source of truth
The account-risk state is derived from:
- `SettingsDomainService.risk_settings()` for configured limits and halt state
- `BrokerPositionRepository` for open/closed broker-backed positions and realized P&L
- `RiskHaltEventRepository` for manual halt/resume audit history
- optional live broker account/order/position snapshots when the execution service can fetch them before submission

## Canonical model
The canonical read model is `AccountRiskState`.

For compatibility, the existing `BrokerRiskAssessment` name remains as an alias so current API consumers do not break during the migration.

## Fields
The canonical model keeps the current risk-assessment contract:
- `allowed`
- `enabled`
- `halt_enabled`
- `halt_reason`
- `reasons`
- `metrics`
- `config`

## Semantics
- `allowed` is the final account-level gate for new trades.
- `halt_enabled` indicates whether the manual kill switch is active.
- `reasons` explains why a trade is blocked or why the account is constrained.
- `metrics` carries the broker-backed exposure and realized-loss counters used by the gate.
- `config` carries the effective risk settings that produced the state.
- If a candidate is provided and a live broker account snapshot includes buying power, risk blocks submission when candidate notional exceeds buying power.
- If live broker positions or open orders are available, they are added to the app-owned exposure counters so risk does not undercount broker-side exposure.
- Live broker snapshot failures are surfaced as metrics warnings; they do not silently look equivalent to healthy broker reconciliation.

## Compatibility
The public `/api/risk` and broker workbench contracts continue to expose the same JSON shape.
The migration only changes the internal canonical type name and service implementation.

## Future migrations
Future work may split the metrics into typed sub-objects, but only if that does not break the operator UI or risk audit history.
