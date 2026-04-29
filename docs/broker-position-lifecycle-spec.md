# Broker position lifecycle spec

**Status:** active v1

This document defines the app-owned lifecycle and performance ledger for positions opened through broker orders submitted by Trade Proposer App.

## Goal

The app must know whether a broker-backed trade actually opened, whether it is still open, how it closed, and what realized P&L it produced.

Broker order status alone is not enough. For Alpaca bracket orders, the parent order being `filled` means the entry filled; the trade outcome is determined by the exit leg or by an explicit position/fill reconciliation path.

## Scope v1

The first implementation must:

- create one broker-position lifecycle record per app-submitted broker order execution
- derive lifecycle state from Alpaca bracket order snapshots returned by order refresh/sync
- persist entry fill price/time, exit fill price/time, realized P&L, realized return percentage, and realized R multiple where available
- mark positions as:
  - `submitted` before entry fill
  - `open` after entry fill and before exit fill
  - `win` when the take-profit leg fills
  - `loss` when the stop-loss leg fills
  - `canceled` when the order is canceled before entry
  - `error` for rejected/failed lifecycle states
  - `needs_review` when the payload is contradictory or incomplete
- expose position records in API/UI so the operator can audit live performance without reading raw broker JSON
- keep the existing broker-order audit trail and raw payloads intact

## Non-goals v1

This release does not yet require:

- Alpaca account activity/fill API ingestion independent from order snapshots
- portfolio-level exposure netting
- automatic stop/target repair when a broker leg disappears
- multi-broker abstraction
- live account support
- fee modeling beyond fields available in broker payloads

## Lifecycle derivation rules

Given a `BrokerOrderExecution` and the latest Alpaca order payload:

1. If the app order has no broker order id or was skipped, no position is created.
2. If the parent order is not filled and has no filled quantity, position status is `submitted` unless the order is canceled/rejected/failed.
3. If the parent entry filled and neither exit leg is filled, position status is `open`.
4. If the bracket take-profit leg (`type=limit`, close side) filled, position status is `win`.
5. If the bracket stop-loss leg (`type=stop` or `stop_limit`, close side) filled, position status is `loss`.
6. If both exit legs appear filled, position status is `needs_review`.
7. If a terminal broker failure occurs before entry, position status is `error` or `canceled` depending on broker status.

## P&L rules

For long positions:

`realized_pnl = (exit_avg_price - entry_avg_price) * quantity`

For short positions:

`realized_pnl = (entry_avg_price - exit_avg_price) * quantity`

`realized_return_pct = realized_pnl / abs(entry_avg_price * quantity) * 100`

`realized_r_multiple = realized_pnl / abs(entry_avg_price - stop_loss) / quantity`

If any required input is missing, the related P&L field remains null and the position stays auditable through raw payloads.

## Persistence requirements

The app must store, at minimum:

- broker order execution id
- recommendation plan id
- run id / job id
- broker / account mode
- ticker / action / side
- quantity and current quantity
- entry order id, entry average price, entry filled at
- exit order id, exit reason, exit average price, exit filled at
- lifecycle status
- realized P&L, realized return percentage, realized R multiple
- raw broker snapshot payload
- error/review message
- created/updated timestamps

## API/UI requirements

Implemented v1 API:

- `GET /api/broker-positions` — list broker position lifecycle records, optionally filtered by `run_id`
- `GET /api/broker-positions/{position_id}` — fetch one broker position lifecycle record

Broker-order UI must show the linked position lifecycle status and realized P&L when available. Position badges must be green for `win`, red for `loss`, warning for `needs_review`/`canceled`, danger for `error`, and neutral/info for submitted/open states.

## Relationship to recommendation outcomes

Broker-position lifecycle is the source of truth for live broker-backed performance. Simulated `RecommendationPlanOutcome` remains useful for research and fallback when no broker execution exists.

## Implementation status

- [x] position lifecycle spec
- [x] broker position persistence table and repository
- [x] lifecycle derivation from Alpaca bracket snapshots during submit/refresh/sync
- [x] API visibility for broker positions
- [x] broker-orders UI position/P&L visibility
- [x] tests for open, win, loss, and P&L derivation
