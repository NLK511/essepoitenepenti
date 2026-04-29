# Broker risk management and kill switch

## Status

Implemented v1.

## Product goal

Aurelio must be able to stop autonomous broker execution before a bad strategy, bad configuration, broker mismatch, or software bug can compound losses. The risk manager is the first guardrail between plan generation and broker submission.

This feature extends, but does not replace:

- Alpaca paper order execution
- broker order audit records
- broker position lifecycle records and realized P&L
- operator settings

## Source of truth

For v1, risk is calculated from app-owned broker position lifecycle records plus the next order candidate being considered.

The broker position lifecycle ledger is the current source of truth for realized broker outcomes. Alpaca account-level reconciliation is intentionally left for a later version because it requires a broader broker-account snapshot and fill/activity model.

## Risk manager responsibilities

Before submitting a new broker order, the app must evaluate whether trading is allowed.

The risk manager blocks new submissions when any of these are true:

1. The manual kill switch is active.
2. The projected number of open/submitted broker positions would exceed the configured maximum.
3. The projected open notional exposure would exceed the configured maximum.
4. The projected single-position notional would exceed the configured maximum.
5. A ticker already has an open/submitted broker position and same-ticker duplicates are disabled.
6. Today's realized broker P&L is at or below the configured daily loss limit.
7. Today's consecutive broker losses are at or above the configured loss streak limit.

Manual resubmission is also blocked by the same risk manager unless the operator first disables the halt or changes the limits.

## Settings

The following settings control v1:

- `risk_management_enabled`: default `true`
- `risk_halt_enabled`: default `false`
- `risk_halt_reason`: operator/system-readable reason
- `risk_max_daily_realized_loss_usd`: default `50`
- `risk_max_open_positions`: default `3`
- `risk_max_open_notional_usd`: default `3000`
- `risk_max_position_notional_usd`: default `1000`
- `risk_max_same_ticker_open_positions`: default `1`
- `risk_max_consecutive_losses`: default `3`

If risk management is disabled, only the manual halt is bypassed along with all risk limits. Disabling it is intended for debugging only.

## Risk metrics

The risk dashboard must expose:

- whether trading is allowed now
- active halt state and reason
- blocking reasons
- today's realized P&L
- today's win/loss counts
- consecutive broker losses today
- open/submitted position count
- open/submitted notional estimate
- configured limits

Open notional estimate uses position entry average price when known, otherwise falls back to the intended order notional from the broker order lifecycle record when available in the position payload. If a reliable notional cannot be inferred, it contributes zero to v1 notional exposure and remains visible as a limitation.

## Order execution behavior

When a plan passes the existing execution checks but fails the risk pre-trade check, the app must persist a skipped broker order audit row instead of silently ignoring the plan.

The skip reason must start with `risk_` and include the blocking reason in `error_message`.

No Alpaca submission may be attempted for a risk-blocked candidate.

## Operator UI

The app must provide a risk dashboard at `/risk` showing current risk state and manual controls:

- Halt trading
- Resume trading
- Refresh

The Settings response also includes risk settings so operators can see the active limits alongside execution settings.

## v1 limitations

- v1 does not yet query Alpaca account positions, open orders, buying power, or account activities directly.
- v1 does not yet calculate unrealized P&L from market prices.
- v1 does not yet liquidate/cancel existing broker exposure automatically when a halt is triggered.
- v1 does not yet store a historical audit trail of halt/resume events beyond the current settings values.

These are deliberate follow-up items after the app has a working kill switch and pre-trade risk gate.
