# Multi-broker execution and risk spec

**Status:** current and target behavior

This document defines the broker execution model used for account-scoped broker execution and the remaining target constraints before any real-money expansion.

## Current behavior

The broker-account abstraction, adapter path, multi-broker fan-out, account-scoped risk controls, drawdown/circuit-breaker state, reconciliation evidence, and broker-aware UI/API surfaces are implemented. Real-money eToro mutation remains disabled/fail-closed.

## Target behavior

Any real-money expansion must preserve account-scoped isolation and must pass external broker validation, production gates, reconciliation evidence checks, and edge-validation standards before mutation is enabled.

## Goal

Trade Proposer App must support **any combination of broker accounts enabled at the same time**. Each broker account must have its own execution settings, credentials, account mode, risk limits, exposure state, reconciliation evidence, and kill-switch behavior.

A broker being enabled or blocked must not silently change another broker's behavior. Every broker candidate must be evaluated, submitted, skipped, halted, and reconciled independently, with an optional global halt above all brokers.

## Broker account model

The app must model execution targets as broker accounts, not as one global selected broker.

A broker account is identified by:

- `broker_account_id`: immutable app-generated id used for persistence, duplicate protection, risk state, and audit joins
- `broker`: for example `alpaca` or `etoro`
- `account_mode`: for example `paper`, `demo`, or `live`
- `account_label`: operator-readable label, for example `alpaca-paper-default` or `etoro-live-main`

`account_label` is mutable display text only. It must never be used as the durable identity for order, position, snapshot, or risk records.

A broker account has:

- enabled/disabled state
- encrypted credentials reference scoped to that broker account, not only to provider name
- autonomous submission enabled/disabled state
- manual-action enabled/disabled state
- symbol allowlist and optional denylist
- supported actions/instruments/order types
- per-order sizing settings
- per-broker risk limits
- per-broker reconciliation snapshots
- per-broker kill switch and reason
- validation status and last validation evidence

The legacy single `broker` setting must be replaced or wrapped by a list of configured broker accounts. eToro demo is the only broker account that startup may create by default. Alpaca paper is legacy fallback code only and must be explicitly configured if it is ever used for regression or rollback work.

## Execution fan-out rules

When proposal generation produces actionable plans:

1. Build one order candidate per `(plan, enabled broker account)` pair.
2. Evaluate each candidate independently against that broker account's capability and risk settings.
3. Persist one broker-order audit row per candidate, including skipped candidates.
4. Submit only candidates that pass that broker account's gates.
5. A failure or halt for one broker account must not block another broker account unless the global halt is active.
6. Duplicate submission protection is scoped by `(run_id, plan_id, broker_account_id)`.
7. Protective order amendments must use the broker adapter `amend_position_protection` contract, not broker-specific raw clients. The contract accepts the broker order id, client order id, symbol, and optional non-risk-increasing stop-loss/take-profit levels, validates the broker snapshot first, and must fail closed when the adapter does not advertise `supports_amend_protection`.
8. Price precision normalization must happen in broker-agnostic order construction before adapter submission. Parent limit prices, stop-loss prices, take-profit prices, resubmitted levels, and amendment levels must be normalized once, persisted in the broker-order audit row, and passed to the adapter through `BrokerOrderRequest` / `BrokerProtectionAmendRequest`. The request model and raw payload must agree exactly so adapters cannot accidentally send unnormalized protective-order prices.
9. The run summary must report broker execution counts grouped by broker account.
10. Candidate creation and duplicate detection must be transactionally safe under concurrent workers. If the app cannot acquire a durable uniqueness lock for a candidate, it must persist/return a skip or warning rather than risk duplicate live orders.

Example: if Alpaca paper and eToro demo are both enabled, a long AAPL plan may create two broker-order rows: one Alpaca paper submission and one eToro demo submission or safety skip. A future eToro live account remains separate and fail-closed unless a separate live rollout is approved.

## Settings

Global settings:

- `broker_execution_enabled`: global autonomous execution master switch, default `false`
- `broker_global_halt_enabled`: global kill switch, default `false`
- `broker_global_halt_reason`: operator/system-readable reason
- `global_max_live_open_notional_usd`: optional aggregate cap across all live broker accounts; if unset, live expansion must still document why per-broker-only limits are sufficient
- `global_max_live_daily_drawdown_usd`: optional aggregate live drawdown cap
- `global_max_live_daily_drawdown_pct`: optional aggregate live drawdown cap
- `global_max_live_order_count_per_day`: optional aggregate live order-count cap
- `broker_accounts`: ordered list of broker account configs

Per-broker-account settings:

- `enabled`: default `false`
- `autonomous_execution_enabled`: default `false`
- `manual_actions_enabled`: default `true` for paper/demo, default `false` for live until acknowledged
- `account_mode`: `paper`, `demo`, or `live`
- `notional_cap_usd`: per-order cap
- `max_open_positions`
- `max_open_notional_usd`
- `max_position_notional_usd`
- `max_same_ticker_open_positions`
- `max_daily_realized_loss_usd`
- `max_consecutive_losses`
- `max_order_count_per_day`
- `min_seconds_between_orders`
- `max_daily_drawdown_usd`
- `max_daily_drawdown_pct`
- `max_total_drawdown_usd`
- `max_total_drawdown_pct`
- `block_on_untracked_exposure`
- `symbol_allowlist`
- `symbol_denylist`
- `allowed_actions`: for example `long` only for eToro live v1
- `max_allowed_leverage`
- `require_protective_stop`: default `true` for live
- `require_take_profit`: default `true` for live
- `demo_validation_required`: default `true` for live
- `demo_validation_artifact_id`: validation evidence for eToro demo accounts before autonomous demo execution is enabled
- `live_acknowledgement`: required before live autonomous execution
- `broker_halt_enabled`
- `broker_halt_reason`
- `snapshot_max_age_seconds`: maximum accepted account/portfolio/equity snapshot age before live submissions are blocked
- `validation_max_age_seconds`: maximum accepted credential/account validation age before live submissions are blocked
- `broker_timezone`: broker-local timezone used for daily limits and drawdown reset

Per-broker demo and live defaults must be conservative. eToro demo should default to low notional, long-only, leverage `1`, autonomous execution disabled until validation, and account-scoped allowlist or denylist support. eToro live must default to `$25` `notional_cap_usd`, long-only, leverage `1`, empty allowlist, autonomous execution disabled, `max_order_count_per_day=1`, and a short snapshot freshness window.

## Risk manager behavior

Risk checks must be performed per broker account and then optionally globally.

A candidate is blocked when any of these are true:

1. Global execution is disabled.
2. Global halt is active.
3. Broker account is disabled.
4. Broker account autonomous execution is disabled.
5. Broker-account halt is active.
6. Credentials or account validation is stale, failed, or missing.
7. The symbol/action/order type is unsupported by the broker account.
8. The symbol is not allowlisted or is denylisted.
9. Protective stop or take-profit is required but missing.
10. The candidate exceeds per-order notional/leverage limits.
11. Projected active positions exceed the broker account limit.
12. Projected open notional exceeds the broker account limit.
13. Same-ticker exposure exceeds the broker account limit.
14. Daily realized loss exceeds the broker account limit.
15. Consecutive losses exceed the broker account limit.
16. Daily order-count or order-frequency limits would be exceeded.
17. Daily drawdown exceeds the broker account limit.
18. Total drawdown exceeds the broker account limit.
19. Configured global live aggregate notional, order-count, or drawdown limits would be exceeded.
20. Broker snapshot is unavailable, stale, contradictory, or has untracked exposure while `block_on_untracked_exposure` is true.
21. Broker API rate-limit, outage, repeated error, or reconciliation circuit breaker is active for that broker account.

Every risk block must persist a skipped broker-order audit row. Error messages must include the broker account id and a stable reason prefix, for example:

- `broker_account_disabled`
- `broker_autonomous_execution_disabled`
- `broker_halt_active`
- `broker_symbol_not_allowlisted`
- `broker_action_not_supported`
- `broker_protective_stop_missing`
- `broker_snapshot_unavailable`
- `broker_untracked_exposure`
- `risk_position_notional_limit_exceeded`
- `risk_open_notional_limit_exceeded`
- `risk_daily_loss_limit_exceeded`
- `risk_order_count_limit_exceeded`
- `risk_daily_drawdown_limit_exceeded`
- `risk_total_drawdown_limit_exceeded`
- `risk_global_live_exposure_limit_exceeded`
- `broker_circuit_breaker_active`

## Drawdown rules

Drawdown checks are mandatory for live broker accounts.

Definitions:

- **Broker equity snapshot:** broker-reported cash/equity/portfolio value at a point in time, plus raw broker payload.
- **Daily starting equity:** first reliable equity snapshot for the broker account after the broker-local trading day starts.
- **Daily high-water equity:** maximum reliable equity snapshot for the broker account during the current broker-local day.
- **Total high-water equity:** maximum reliable equity snapshot persisted for the broker account across all days since tracking started.
- **Daily drawdown USD:** `daily_high_water_equity - current_equity`.
- **Daily drawdown pct:** `daily_drawdown_usd / daily_high_water_equity * 100`.
- **Total drawdown USD:** `total_high_water_equity - current_equity`.
- **Total drawdown pct:** `total_drawdown_usd / total_high_water_equity * 100`.

If current equity or high-water equity cannot be trusted, live submissions for that broker account must be blocked with `risk_drawdown_evidence_unavailable`.

Drawdown state must be persisted per broker account so a service restart cannot reset drawdown protection.

When the app has no prior high-water mark for a live account, it must enter a drawdown warm-up state. In warm-up, autonomous live submission is blocked until the operator records an initial baseline from a trusted broker snapshot or an implementation-specific validation routine establishes it. A missing baseline must never be treated as zero drawdown.

Daily boundaries use `broker_timezone`. The app must persist the boundary used for each drawdown record so daylight-saving changes and service restarts cannot shift an already-recorded trading day.

## Broker adapter API contract

Each broker adapter must implement and be tested against the same contract:

- `validate_credentials()`
- `get_account_snapshot()`
- `get_open_orders()`
- `get_open_positions()`
- `resolve_instrument(symbol)`
- `submit_open_order(candidate)`
- `lookup_order(order_id | reference_id)`
- `cancel_order(order_id)`
- `close_position(position_id, units_to_deduct | full_close)`
- `list_trade_history(start_date, page, page_size)`
- `get_equity_snapshot()` or equivalent equity fields from account/portfolio endpoints

Adapter responses must be normalized into broker-agnostic models while retaining raw payloads.

Adapters must also expose capability metadata before order construction:

- supported asset classes and markets
- supported order types
- support for fractional units vs cash amount sizing
- stop-loss/take-profit support and known constraints
- short/leverage/CFD availability
- rate limits and retry policy
- whether order lookup is strongly consistent or may lag after submission

If capabilities are unavailable or ambiguous for a live broker account, live submission must be blocked.

## Failure handling, rate limits, and circuit breakers

Each broker account must have a circuit breaker. The circuit breaker blocks new autonomous submissions for that broker account when:

- repeated broker API failures exceed the configured threshold
- broker returns rate-limit responses and retry-after cannot be safely honored
- order submission succeeds but lookup/reconciliation cannot confirm state within the configured window
- account/portfolio/equity snapshots are stale or contradictory
- secret validation fails after previously passing

Retries must be bounded and idempotent. Opening orders must never be retried with a new idempotency key unless the previous attempt is proven not accepted by the broker or the operator explicitly performs a reviewed resubmit. For live accounts, unknown submission outcome means `needs_review` plus broker-account circuit breaker, not automatic retry.

## Persistence and audit requirements

Every broker-account execution record must persist:

- immutable `broker_account_id`
- broker, account mode, account label at time of action
- endpoint/method/action name
- idempotency/request id
- request payload and response payload with secrets redacted
- normalized status and raw broker status
- risk decision inputs and blocking reasons
- snapshot ids used for pre-trade checks
- created/updated timestamps and correlation ids

Secrets and bearer/user keys must be redacted before persistence. Redaction must be tested against nested payloads, headers, observability events, UI responses, and failure logs.

## Main API-call test requirements

Every broker adapter must have fake-client tests for all main API calls before autonomous submission can be enabled:

### Opening

- successful open-order request/response is persisted
- rejected open-order response is persisted and does not retry silently
- duplicate `(run_id, plan_id, broker account)` submission is blocked
- missing stop/take-profit blocks live orders when required
- request id/idempotency key is unique per attempt and persisted
- unknown submission outcome triggers `needs_review` and broker-account circuit breaker, not blind retry
- broker rate-limit response is recorded and blocks further autonomous submissions until safe

### Closing

- successful full close marks local position `closing` immediately
- successful partial close records units deducted and leaves remaining exposure active
- rejected close does not change lifecycle to `closing`
- close of non-app-owned position is blocked unless explicitly reviewed and separately confirmed

### Canceling

- pending order cancel succeeds and is persisted
- terminal/filled order cancel is idempotent and does not create a false failure
- live cancel requires explicit operator confirmation semantics

### Lookup and reconciliation

- order lookup maps pending/open/filled/rejected/canceled states correctly
- portfolio open positions reconcile to app-owned lifecycle records
- closed trade history maps realized P&L to `win`, `loss`, or `needs_review`/`closed_flat`
- contradictory order/portfolio/history evidence maps to `needs_review`
- stale reconciliation snapshots or contradictory/missing broker evidence for app-owned active positions activate the broker-account circuit breaker
- untracked broker exposure blocks new live submissions

### Exposure and drawdown

- projected open-position count blocks correctly
- projected open notional blocks correctly
- same-ticker exposure blocks correctly
- daily realized loss blocks correctly
- consecutive losses block correctly
- daily max drawdown USD and pct block correctly
- total max drawdown USD and pct block correctly
- global aggregate live exposure/drawdown limits block correctly when configured
- missing/stale equity snapshot blocks live broker accounts
- missing baseline/high-water mark creates warm-up block, not zero drawdown
- drawdown high-water marks persist across service restarts

### Multi-broker behavior

- enabling two broker accounts creates two independent candidates per actionable plan
- one broker account being halted does not block another broker account
- global halt blocks all broker accounts
- per-broker notional and exposure settings are applied independently
- run summaries group submitted/skipped/rejected counts by broker account
- UI/API filters can isolate broker/account-mode/account-label records
- mutable account labels do not break duplicate detection, reconciliation, or historical audit because `broker_account_id` is immutable

## UI/API requirements

The Execution & Risk workbench must be broker-account aware:

- list configured broker accounts and their enabled/halted/validated state
- show per-broker risk metrics and limits
- show per-broker drawdown state and high-water evidence
- show global halt separately from broker-account halts
- filter orders and positions by broker/account mode/account label
- make live broker accounts visually distinct from paper/demo accounts
- require stronger confirmation for live manual cancel/close/resubmit actions

Settings API must read/update broker accounts without exposing credentials.

Risk API must return:

- global risk state and aggregate live exposure/drawdown state when configured
- one risk state per broker account
- per-broker blocking reasons
- per-broker exposure metrics
- per-broker drawdown metrics
- latest snapshot evidence timestamps
- broker-account circuit-breaker state and reason

## Current behavior and target gates

Canonical current behavior includes broker-account settings, default eToro demo bootstrap, account-scoped credentials, redacted broker-account APIs, per-broker risk/drawdown/circuit-breaker state, broker adapter contracts, Alpaca paper retained only as an explicit legacy adapter fallback, broker-agnostic price normalization, multi-broker fan-out with per-account skips/submissions, broker-aware workbench APIs/UI, reconciliation evidence, and eToro read-only/demo-shadow/fail-closed adapter tests.

Still target/gated:

- eToro demo lifecycle against current external demo endpoints with operator-provided demo credentials
- continued external eToro demo lifecycle evidence before autonomous demo execution is enabled
- real eToro live mutation enablement; live adapter currently fails closed with `etoro_live_mutation_disabled`
- production-grade external validation artifacts and release-readiness evidence before live micro-size rollout
- measured broker-backed trading edge before increasing live scope or notional caps
