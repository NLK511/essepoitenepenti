# Broker steering safety audit — 2026-06-08

**Status:** current audit summary  
**Scope:** broker-position steering dry-run review, protective-order evidence fix, lifecycle/freshness gates, and local ledger cleanup after operator broker review.

## Why this audit exists

A steering dry-run originally looked actionable because all active app positions had protective-order evidence after backfill. Manual review showed that was not enough: the app ledger still contained expired, stale, duplicated, or partially filled broker positions that did not match actual broker exposure.

The key lesson is simple:

> Steering must not mutate broker orders unless the position is fresh, broker-confirmed, non-expired, quantity-correct, and has normalized active protective-order evidence.

## What was fixed

- Added broker-neutral protective-order evidence to broker positions:
  - stop-loss order id/status/price
  - take-profit order id/status/price
  - verification timestamp/source
- Kept `exit_order_id` reserved for the filled closing order only.
- Changed steering to use normalized protective-order evidence instead of Alpaca-specific child-order payloads.
- Added lifecycle/freshness gates:
  - expired holding period blocks amendment and routes to `manual_review_required`
  - stale/missing reconciliation blocks mutation
  - submitted zero-quantity position rows are not amendable open positions
  - missing active protective orders blocks mutation
- Added stale ledger reporting and safe `needs_review` marking tooling.
- Updated dry-run quality reporting so safe manual-review/cancel decisions are not counted as suspicious expired amendments.

## Operator broker review result

The broker showed only these real holdings before reset:

```text
A    qty 7
AAPL qty 2
ARM  qty 1
TXN  qty 2
```

Aurelio's ledger did not match most of that exposure:

- `A` matched exactly and had SL/TP evidence.
- `AAPL`, `ARM`, and `TXN` were quantity/lifecycle mismatches due to partial fills or stale rows.
- many older rows were already closed by broker TP/SL fills but were still active locally.

Therefore autonomous steering remained disabled.

## Cleanup performed

All cleanup was local to Aurelio. No broker mutation endpoints were used.

1. Marked stale/mismatched active broker-position rows `needs_review`.
2. Marked stale/mismatched active broker-order rows `needs_review`.
3. After the operator manually sold all broker positions, marked the remaining local active row/order `needs_review` too.

Final local steering state after cleanup:

```text
active_app_position_rows: 0
open_amendable_rows: 0
quantity_zero_submitted_rows: 0
steering_candidates: 0
```

## Artifacts

- `artifacts/steering-dry-run-quality-after-freshness-gates.json`
- `artifacts/steering-dry-run-review-after-freshness-gates.csv`
- `artifacts/steering-dry-run-reviewed-summary-after-freshness-gates.json`
- `artifacts/manual-broker-reconciliation-review-2026-06-08.json`
- `artifacts/manual-broker-reconciliation-cleanup-applied-2026-06-08.json`
- `artifacts/manual-broker-order-ledger-cleanup-applied-2026-06-08.json`
- `artifacts/operator-sold-all-local-ledger-block-2026-06-08.json`
- `artifacts/stale-broker-positions-after-sold-all.json`

## Future recovery checklist

Before enabling steering mutation again, require:

1. Broker UI/API confirms zero open positions and zero open orders after the manual reset.
2. New positions are created by Aurelio from a clean baseline.
3. Reconciliation snapshots are fresh.
4. Position quantity equals broker-confirmed filled quantity.
5. Holding period is not expired.
6. Active SL/TP evidence is present in normalized fields.
7. Dry-run produces enough fresh amendment/close samples for review.
8. Operator approves turning off dry-run.

Until then, keep:

```text
steering_enabled=true
steering_dry_run=true
```

and do not enable broker mutation.
