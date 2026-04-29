# Alpaca paper order execution spec

**Status:** active

This document defines the first automated order-execution integration for Trade Proposer App.

## Goal

After proposal generation, the app should be able to submit actionable plans to **Alpaca paper trading** automatically.

This feature is order execution only. It does not change plan generation, calibration, or outcome evaluation.

## Scope v1

The first version must:

- run only in **paper** mode
- submit orders only for actionable plans (`long` and `short`)
- place **one order per plan**
- use the plan’s execution levels:
  - entry point
  - stop loss
  - take profit
- use a default notional size of **$1,000 per plan** from Settings
- round quantity down to whole shares
- record every broker submission in the database
- keep the run inspectable in the UI and API
- expose a dedicated Broker Orders page and a run-detail broker-orders panel for operator audit/review
- allow manual resubmit/cancel actions for submitted broker orders when the broker and order state permit it

## Order construction rules

For each actionable `RecommendationPlan`:

1. Skip the plan if entry, stop-loss, or take-profit levels are missing.
2. Compute the entry reference from the plan’s entry zone.
   - If both `entry_price_low` and `entry_price_high` exist, use their midpoint.
   - If only one side exists, use that side.
3. Compute quantity from the configured notional cap:
   - `quantity = floor(notional_cap / entry_reference)`
4. Skip the plan if the computed quantity is less than 1.
5. Submit a **limit bracket order** to Alpaca paper trading.
6. Normalize prices to Alpaca-valid tick sizes before submission:
   - prices at or above $1.00 use 2 decimal places
   - prices below $1.00 use 4 decimal places
7. Attach the stop-loss and take-profit levels to the parent order.

### Side mapping

- `long` plan -> buy order
- `short` plan -> sell order

## Safety rules

- Paper trading only.
- If execution is disabled in settings, the system must not submit orders.
- Duplicate order submission for the same plan/run pair must be avoided.
- Broker failures should be recorded and surfaced as warnings, not silently ignored.
- Manual resubmit/cancel actions must be idempotent enough to avoid duplicate client-order ids and must only target valid order states.

## Persistence requirements

The app must store, at minimum:

- plan id
- run id
- broker name
- broker order id
- client order id
- order side
- order type
- quantity
- notional cap used
- entry/stop/take-profit levels
- submission status
- raw request/response payloads
- any broker error message

## Run-level reporting

Proposal-generation runs should include order-execution summary data in their stored run summary/artifact so operators can see:

- how many actionable plans were submitted
- how many were skipped
- how many were rejected by the broker
- how many warnings occurred

## Non-goals for v1

This first release does **not** include:

- live trading accounts
- portfolio-level risk netting
- partial-fill rebalancing
- advanced position sizing
- automated exit-order management after submission beyond explicit operator actions
- broker-agnostic abstraction beyond Alpaca

## API surface

Implemented endpoints:
- `GET /api/broker-orders` — list broker orders, optionally filtered by `run_id`
- `GET /api/broker-orders/{execution_id}` — fetch one broker order
- `POST /api/broker-orders/{execution_id}/resubmit` — resubmit a failed/canceled order using a fresh client-order id
- `POST /api/broker-orders/{execution_id}/cancel` — cancel an order on Alpaca paper and persist the canceled state
- `POST /api/broker-orders/{execution_id}/refresh` — refresh one order from Alpaca and persist the latest broker status
- `POST /api/broker-orders/sync` — refresh the app’s open broker orders in a small batch

Run detail also exposes `broker_order_executions` so the operator can see execution history without leaving the run page.

When broker execution records exist for a plan, the operator UI should prefer the broker-backed evaluation state over the simulated plan outcome for the primary status badge. Terminal broker failures (`failed`, `rejected`, `canceled`, `expired`) should not be shown as pending broker evaluation; they count as missing broker evaluation and may fall back to simulated resolution if one exists. For Alpaca bracket orders, the parent order being `filled` only means the entry was filled and the position may still be open. Broker-backed win/loss evaluation must come from the bracket exit legs: a filled take-profit leg is a win, and a filled stop-loss leg is a loss. Parent-filled orders with no filled exit leg are open entries, must continue to be refreshed, and must not be counted as wins or losses yet. The simulated outcome remains available as secondary context.

## Implementation status

- [x] Alpaca paper client
- [x] broker order persistence table
- [x] execution service hooked into proposal generation
- [x] API visibility for submitted orders
- [x] dedicated Broker Orders page
- [x] run-detail broker-orders panel
- [x] manual resubmit/cancel/refresh controls for valid paper orders
- [x] automatic broker-order reconciliation during market hours
- [x] Alpaca bracket exit-leg detection for open-entry, closed-win, and closed-loss states
- [x] tests for order sizing, submission handling, price normalization, cancel/resubmit/refresh handling, bracket exit-leg classification, route visibility, and broker-vs-simulated evaluation precedence in plan views
