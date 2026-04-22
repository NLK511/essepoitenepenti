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
- use a fixed notional size of **$1,000 per plan**
- round quantity down to whole shares
- record every broker submission in the database
- keep the run inspectable in the UI and API

## Order construction rules

For each actionable `RecommendationPlan`:

1. Skip the plan if entry, stop-loss, or take-profit levels are missing.
2. Compute the entry reference from the plan’s entry zone.
   - If both `entry_price_low` and `entry_price_high` exist, use their midpoint.
   - If only one side exists, use that side.
3. Compute quantity from the notional cap:
   - `quantity = floor(1000 / entry_reference)`
4. Skip the plan if the computed quantity is less than 1.
5. Submit a **limit bracket order** to Alpaca paper trading.
6. Attach the stop-loss and take-profit levels to the parent order.

### Side mapping

- `long` plan -> buy order
- `short` plan -> sell order

## Safety rules

- Paper trading only.
- If execution is disabled in settings, the system must not submit orders.
- Duplicate order submission for the same plan/run pair must be avoided.
- Broker failures should be recorded and surfaced as warnings, not silently ignored.

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
- exit-order management after submission
- broker-agnostic abstraction beyond Alpaca

## Implementation status

- [x] Alpaca paper client
- [x] broker order persistence table
- [x] execution service hooked into proposal generation
- [x] API visibility for submitted orders
- [x] tests for order sizing and submission handling
