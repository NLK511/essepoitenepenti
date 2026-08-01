# eToro live trading integration spec

**Status:** current and target behavior

This document defines the required behavior for eToro as a broker integration for Trade Proposer App.

## Current behavior

Read-only plumbing, demo/mock lifecycle plumbing, live-shadow audit rows, broker-account gates, and a fail-closed live adapter are implemented. Real-money eToro mutation is not enabled.

## Target behavior

Safety requirements in this spec remain mandatory before any live mutation path can be activated. Any future live path must pass external validation, release-readiness, production-readiness, and edge-validation gates.

## External API basis

The integration was originally based on the official eToro Developer Portal observed on 2026-06-01. The demo migration refreshed the endpoint basis on 2026-07-24 against the official OpenAPI `v1.311.0`:

- Documentation: `https://api-portal.etoro.com`
- Base URL: `https://public-api.etoro.com`
- Authentication headers:
  - `x-api-key` — public application/API key
  - `x-user-key` — user account key
  - `x-request-id` — unique UUID per request, used by the app as the idempotency/audit request id
- Key generation path documented by eToro: eToro account `Settings > Trading > API Key Management`
- Relevant current demo endpoints:
  - `GET /api/v1/market-data/search` — resolve symbol to eToro instrument id
  - `GET /api/v1/market-data/instruments/rates` — fetch current rates
  - `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}` —
    fetch OHLCV candles for explicit market-data validation and future bar
    provider support. This endpoint must not be used by replay/tuning paths
    directly; it may hydrate the canonical bars cache only through explicit
    refresh/backfill/validation jobs.
  - `POST /api/v2/trading/execution/demo/orders` — create demo order
  - `GET /api/v2/trading/info/demo/orders:lookup` — lookup demo order by order id or reference id
  - `DELETE /api/v2/trading/execution/demo/orders/{orderId}` — cancel pending demo order
  - `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}` — close all or part of a demo position
  - `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}` — cancel pending demo close order
  - `GET /api/v1/trading/info/demo/portfolio` — demo portfolio breakdown
  - `GET /api/v1/trading/info/demo/pnl` — demo account portfolio and P&L summary
  - `GET /api/v1/trading/info/demo/aggregate-portfolio` — demo aggregated portfolio snapshot
  - `GET /api/v1/trading/info/demo/close-orders/{orderId}` — demo close-order lookup
  - `GET /api/v1/trading/info/trade/demo/history` — demo closed trade history. OpenAPI
    `v1.311.0` documents this route, but current Demo runtime returned `404` during
    validation on 2026-07-24. The app must therefore treat history as optional
    evidence, not as the authority for exits.
  - `POST /api/v2/trading/info/demo/eligibility` — demo instrument eligibility
  - `POST /api/v2/trading/info/demo/costs` — demo what-if costs
  - `PATCH /api/v2/trading/demo/positions/{positionId}` — modify demo stop-loss and take-profit settings
- Relevant current real endpoints remain documented for future validation only:
  - `POST /api/v2/trading/execution/orders` — create real order
  - `GET /api/v2/trading/info/orders:lookup` — lookup real order by order id or reference id
  - `DELETE /api/v2/trading/execution/orders/{orderId}` — cancel pending real order
  - `POST /api/v1/trading/execution/market-close-orders/positions/{positionId}` — close all or part of a real position
  - `GET /api/v1/trading/info/portfolio` — real account portfolio/open positions/open orders
  - `GET /api/v1/trading/info/real/pnl` — real account portfolio and P&L summary
  - `GET /api/v1/trading/info/trade/history` — closed trade history

Current implementation status: read-only eToro client, demo adapter plumbing, and a fail-closed live adapter are implemented. The live adapter advertises live account mode but rejects submit/cancel/close with `etoro_live_mutation_disabled` and must not call live mutation endpoints. Current migration work is limited to demo endpoints from OpenAPI `v1.311.0`; Real mutation remains out of scope.

If eToro changes endpoint names, payload semantics, or permission behavior, implementation must update this spec before code is changed. Before implementing any live mutation, the implementation task must re-read the current eToro docs and record the exact demo and real endpoint paths used. If a documented demo endpoint differs from the real endpoint path, tests must cover both mappings.

## Goal

Trade Proposer App must support eToro demo as the first-class paper-trading broker, with enough safety controls to submit, reconcile, and audit broker activity without relying on broker UI inspection as the primary control. Startup defaults, legacy order-execution settings, and operator-facing execution controls must point to eToro demo. Alpaca paper may remain as explicit legacy adapter code for regression or rollback work, but it must not be auto-bootstrapped or presented as the default broker.

The integration must allow an operator to:

1. Store eToro credentials securely.
2. Enable one or more eToro broker accounts alongside any other broker accounts.
3. Validate credentials and account mode without placing an order.
4. Run read-only portfolio and market-data checks.
5. Run demo eToro order submission and reconciliation.
6. Keep live eToro trading disabled unless a future explicit live-mutation plan passes separate safety gates.
7. See every request, response, position, close, error, and safety block in the existing broker-order and broker-position UI/API.

## Non-negotiable safety principles

1. **Default off:** eToro live trading is disabled by default in every environment.
2. **Two-step live enablement:** enabling an eToro broker account is not enough. That broker account must have live trading explicitly enabled, and both the global halt and that broker account's halt must be off.
3. **Demo-first:** this migration may submit only to eToro Demo. Live order submission must remain blocked regardless of demo success until a separate operator-approved live implementation exists.
4. **Small first money:** initial live notional caps must be stricter than general broker caps. The first implementation must default to no more than `$25` per live eToro order until an operator raises it.
5. **No leverage by default:** live eToro orders must use `leverage: 1`. Any leveraged or CFD-specific behavior is out of scope until separately specified and tested.
6. **Long-only initial live scope:** live eToro v1 must skip short plans. Short/CFD support is a future spec because it changes real-money risk and broker semantics.
7. **Instrument allowlist:** live eToro v1 must only trade symbols explicitly allowlisted by the operator. Non-allowlisted plans are persisted as skipped broker orders.
8. **Real account drift blocks trading:** if eToro portfolio/open-order snapshots show open exposure not linked to app-owned broker-position records, new live submissions must be blocked until reviewed.
9. **Every skip is auditable:** safety blocks must persist broker-order audit rows with explicit `status=skipped` and a specific `error_message` prefix.
10. **No silent fallback:** if eToro submission, lookup, portfolio, or history parsing is uncertain, the app must halt new eToro submissions instead of guessing.
11. **Unknown accepted state is dangerous:** if a live open/close/cancel request times out or returns an ambiguous response, the eToro broker account must enter `needs_review`/circuit-breaker state until broker lookup and portfolio evidence prove the outcome.
12. **Permissions must be explicit:** live trading requires credentials whose validated permission set includes real trading. Read-only or demo-only keys must never be allowed to submit real orders.

## Scope v1

The demo-first eToro implementation must include:

- eToro credential storage and validation
- broker-account support so eToro can be enabled together with Alpaca or any future broker
- eToro client for read-only demo account, market-data, and demo trading endpoints
- order submission for actionable `long` plans only
- fixed USD amount sizing, not unit sizing, for eToro demo v1
- stop-loss and take-profit rates included in the open-order payload whenever provided by the plan
- one eToro order per plan
- eToro instrument-id lookup with local caching
- idempotency via persisted `x-request-id`/client request id
- order lookup and cancellation for pending orders
- market close for open app-owned eToro positions
- reconciliation from order lookup, portfolio, P&L, and trade-history endpoints
- broker-order and broker-position persistence using the existing audit/lifecycle tables where possible
- UI/API visibility in the existing Execution & Risk workflow
- risk manager integration using eToro demo snapshots before every demo submit/resubmit where available
- eToro permission/scope validation, including detecting read-only, demo-enabled, expired, revoked, or wrong-environment keys where eToro exposes enough evidence
- eToro broker capability validation for each allowlisted instrument before any demo order is accepted

## Out of scope v1

- leveraged trading
- short/CFD trading
- crypto-specific wallet/transfer behavior
- options/futures
- copy trading and eToro Agent Portfolios
- multi-user account delegation
- automatic liquidation on halt
- automatic broad cancel-all on halt
- position scaling, pyramiding, or partial profit-taking beyond explicit operator close
- trusting simulated outcomes over broker evidence for live performance
- demo order submission for instruments whose eToro product type, exchange, currency, market-hours behavior, minimum size, or protective-order constraints have not been validated and cached

## Broker abstraction requirements

## eToro Demo exit reconciliation

The normal broker sync path must reconcile eToro Demo exits without relying on broker UI
inspection.

Required evidence order:

1. `GET /api/v2/trading/info/demo/orders:lookup` is the entry-order lifecycle signal.
   `positionExecutions[].state=open` keeps a local position active. A `closed` or
   `closing` state removes active exposure.
2. `GET /api/v1/trading/info/demo/portfolio` is the open-exposure authority. A local
   eToro Demo position that is missing from the broker portfolio must not count as
   active risk even if earlier entry-order evidence was filled.
3. `GET /api/v1/trading/info/demo/close-orders/{orderId}` is the close-order evidence
   source when the app has an `exit_order_id`. It must populate close rate/time/units
   from the close-order `positions[]` rows. It may populate realized P&L only when the
   close-order payload explicitly provides it.
4. `GET /api/v1/trading/info/trade/demo/history` may be used only when it succeeds. A
   `404` or unavailable history result must not fail reconciliation and must not cause
   guessed realized P&L.

If order lookup says a position is closed, or the portfolio no longer contains that
position, but no close-order/history evidence confirms realized P&L, the local position
must be marked `needs_review`, set `current_quantity=0`, set
`current_unit_quantity=0`, preserve the raw broker evidence, and stop counting it as
active exposure.

If close-order evidence confirms an exit, the position must store:

- `exit_order_id`
- `exit_avg_price`
- `exit_filled_at`
- `current_quantity=0`
- `current_unit_quantity=0`
- `status=win` when confirmed realized P&L is positive
- `status=loss` when confirmed realized P&L is negative
- `status=needs_review` when realized P&L is unavailable or zero

Rejected eToro orders, including post-execution reverse-close cases, must remain
non-active and keep the broker error payload in the audit row.

The Alpaca-specific execution path has been separated behind the broker-account adapter defined in `multi-broker-execution-risk-spec.md` while preserving Alpaca paper behavior. Existing Alpaca tests remain the regression suite for the abstraction. eToro-specific tests must cover every eToro API call used for opening, closing, canceling, lookup, portfolio snapshots, trade history, and drawdown/equity evidence before any external demo/live mutation path is enabled.

## eToro order construction rules

For each actionable plan considered for eToro demo v1:

1. Skip if action is not `long`.
2. Skip if execution levels are missing: entry, stop loss, or take profit.
3. Skip if the ticker is not in the eToro demo allowlist when an allowlist is configured.
4. Resolve the eToro `instrumentId` from the plan ticker/symbol.
5. Validate the resolved instrument against cached eToro metadata: product type, exchange/market, base currency, tradability, minimum/maximum order amount, stop-loss/take-profit constraints, market hours, and whether the instrument is traded as underlying asset or CFD.
6. Compute entry reference from the plan entry zone using the existing midpoint rule.
7. Use the configured eToro demo notional cap as the payload `amount`, then clamp/block according to broker minimums, operator maximums, demo account cash, and per-broker risk caps.
8. Enforce all risk-manager caps before submission.
9. Submit only market open orders unless a later spec adds MIT/limit behavior. Market orders must include a pre-submit latest-price/slippage sanity check when eToro market data is available; if the latest price is outside the plan entry zone by more than the configured tolerance, skip with `etoro_price_outside_entry_tolerance`.
10. Submit payload with:
   - `action: "open"`
   - `transaction: "buy"`
   - `symbol`
   - `instrumentId`
   - `orderType: "mkt"`
   - `leverage: 1`
   - `amount`
   - `orderCurrency: "usd"`
   - `stopLossRate` from the plan stop-loss level
   - `takeProfitRate` from the plan take-profit level
   - `stopLossType: "fixed"`
11. Persist the exact request headers minus secrets, request body, response body, endpoint, and `x-request-id`.

If eToro rejects a payload because a stop-loss/take-profit value violates broker constraints, the order must be recorded as rejected. The app must not retry without the protective level unless the operator manually performs a separate explicitly labeled action.

If eToro supports both underlying assets and CFDs for a symbol, v1 demo must block unless instrument metadata proves the intended non-leveraged underlying/cash product is being traded. Ambiguous product mapping is `etoro_instrument_ambiguous`.

## Settings

eToro settings live inside one or more broker-account configs defined in `multi-broker-execution-risk-spec.md`. The default broker account is `etoro-demo-main`, disabled for autonomous execution until validation gates pass. Additional broker accounts may be configured explicitly, but Alpaca paper must not be created by startup as a default account.

Required eToro broker-account settings:

- `enabled`: default `false`; allows read-only/demo eToro use for this account when credentials exist
- `account_mode`: `demo` or `live`
- `autonomous_execution_enabled`: default `false`; allows autonomous submission for this eToro account only
- `demo_validation_artifact_id`: recommended before enabling autonomous demo execution after external credential/lifecycle validation
- `live_trading_enabled`: default `false` for live accounts; allows real-order submission only when all safety gates pass
- `live_acknowledgement` / `live_acknowledged`: operator-entered confirmation text/timestamp or server boolean required before live enablement
- `live_shadow_enabled`: default `false`; when true, the server stores a would-submit audit row and never calls a mutation endpoint
- `max_entry_slippage_pct`: optional latest-price tolerance around the plan entry range; when set, missing price blocks live submission
- `notional_cap_usd`: default `25` for live, must also respect this account's `max_position_notional_usd`
- `symbol_allowlist`: default empty list for live
- `require_demo_validation`: default `true` for live
- `block_on_untracked_exposure`: default `true`
- `max_allowed_leverage`: default `1`
- per-broker exposure, drawdown, and loss limits from `multi-broker-execution-risk-spec.md`

Credentials must be stored as encrypted broker-account credentials. The `x-user-key` is a secret and must never appear in logs, raw payloads, UI, test snapshots, or observability events. If the same eToro login has both demo and live keys, they must be stored as separate broker-account credentials and validated independently.

## Risk management integration

The existing broker risk manager remains the gate between plan generation and broker submission.

For eToro live, pre-submit risk must additionally capture and persist:

- real account portfolio snapshot
- open orders
- open positions
- real P&L snapshot when available
- matched app-owned positions
- untracked eToro positions/orders
- available cash/equity evidence used for the decision

Trading is blocked when:

- the global halt or this eToro broker account's halt is active
- global broker execution is disabled
- this eToro broker account is disabled
- autonomous execution is disabled for this eToro broker account
- `live_trading_enabled` is false for this eToro live account
- live operator acknowledgement is missing for this eToro live account
- demo validation is required but missing for this eToro live account
- any current per-broker-account risk-manager limit blocks the candidate, including exposure, realized loss, consecutive loss, and drawdown limits
- eToro credentials fail validation
- eToro account/portfolio snapshot is unavailable or ambiguous
- eToro reports untracked real exposure and this broker account's `block_on_untracked_exposure` is true
- the candidate would exceed this eToro account's notional, exposure, drawdown, or symbol allowlist limits
- the resolved instrument metadata suggests unsupported leverage, market, currency, trading session, minimum order size, protective-order constraint, or product type for v1
- latest price/slippage sanity check fails or cannot be performed when required
- eToro API rate-limit/outage/circuit-breaker state is active for this broker account

Safety-blocked rows must use specific prefixes, for example:

- `etoro_live_trading_disabled`
- `etoro_live_acknowledgement_missing`
- `etoro_demo_validation_missing`
- `etoro_symbol_not_allowlisted`
- `etoro_short_not_supported_v1`
- `etoro_untracked_exposure`
- `etoro_snapshot_unavailable`
- `risk_position_notional_limit_exceeded`
- `etoro_price_unavailable`
- `etoro_price_outside_entry_tolerance`
- `etoro_instrument_ambiguous`
- `etoro_permission_missing`
- `etoro_live_shadow_would_submit`
- `broker_circuit_breaker_active`

## Reconciliation and lifecycle rules

eToro broker-position lifecycle must be broker-first and must not infer wins/losses from simulated plan outcomes.

Lifecycle evidence priority:

1. Order lookup by `orderId` or `referenceId`.
2. Current portfolio/open positions/open orders.
3. Real P&L endpoint.
4. Trade history for closed positions.
5. Raw broker payload review if the above contradict each other.

Order lookup may lag immediately after submission. During this window the local lifecycle may remain `submitted`, but any ambiguous live response must also set the broker-account circuit breaker until lookup/portfolio evidence converges.

Lifecycle mapping:

- submitted/pending eToro order -> local `submitted`
- executed open order with resulting position id -> local `open`
- pending explicit app close request -> local `closing`
- trade-history closed row with positive net profit -> local `win`
- trade-history closed row with negative net profit -> local `loss`
- trade-history closed row with zero net profit -> local `closed_flat` if supported by schema, otherwise `needs_review` until schema supports it
- canceled before entry -> local `canceled`
- rejected/failed -> local `error`
- contradictory position/order/history evidence -> local `needs_review`

The app must persist eToro `positionId`, `orderId`, `referenceId`, `instrumentId`, open/close rates, open/close timestamps, net profit, fees, taxes where available, units, leverage, amount, stop loss, take profit, and raw snapshots when available.

Partial fills and partial closes must keep remaining exposure active. A position may not move to final `win`/`loss` until closed-trade evidence accounts for the full app-owned position quantity or the unresolved remainder is explicitly marked `needs_review`.

## Operator UI/API requirements

The existing broker workbench must make real-money state impossible to miss:

- show enabled broker accounts and account modes in the page header
- show a prominent `LIVE ETORO` badge whenever any eToro live account is enabled or live eToro records exist
- show whether eToro live trading is disabled, enabled, halted, or blocked by validation
- show eToro credential validation status without exposing secrets
- show live notional cap, order-count limit, drawdown limits, current drawdown, demo-validation artifact evidence, and symbol allowlist
- show untracked eToro exposure warnings at the top of Execution & Risk
- allow operators to record demo-validation artifact ids and clear broker-account circuit breakers from the Execution & Risk broker-account cards, while server-side APIs enforce validation and reason requirements
- require an explicit confirmation dialog for manual resubmit/cancel/close on eToro live records; server-side broker-order resubmit/cancel and broker-position close must require exact text `CONFIRM LIVE ETORO {broker_account_id} {operation}` and must respect `manual_actions_enabled`. Real eToro live close remains fail-closed with `etoro_live_mutation_disabled` until live mutation enablement is separately reviewed
- separate demo and live records with filters by broker account, broker, account mode, status, and run id in both API and Execution & Risk frontend
- preserve raw request/response audit detail with secret redaction

Existing API endpoints may be reused, but responses must include enough broker/account-mode metadata for the UI to render eToro live risk clearly. The broker workbench payload must include redacted broker-account state, live/demo/paper badges, credential presence, drawdown/circuit-breaker state, global live caps, and aggregate live-account usage. The Execution & Risk frontend must make eToro live records visually distinct, display broker-account ids on order detail, and prompt for the exact server-required live eToro confirmation text before manual resubmit/cancel. Broker-account API responses must redact credential material in validation evidence and risk settings while exposing operator-visible live/demo/paper badges, drawdown state, circuit-breaker state, and whether account-scoped credentials exist. Broker-account API controls may update labels, halt state, allowlist/denylist, notional/open-position caps, live risk settings, and demo-validation artifact evidence, but responses must remain redacted. The broker risk API must expose global live caps and aggregate live-account usage so the operator can verify live notional and daily order-count limits before enabling micro-size trading.

## Observability

The integration must emit structured observability events for:

- credential validation success/failure
- instrument resolution/cache miss
- pre-submit risk assessment
- safety skip
- order submit request/response summary
- order lookup/reconciliation
- close/cancel request/response summary
- untracked exposure detection
- live trading enable/disable setting changes
- eToro circuit-breaker activation/clearance
- eToro permission/capability validation changes

Events must redact credentials and must include correlation ids, broker, account mode, run id, plan id, ticker, and broker order/position ids when available.

## Required test suite before implementation can be considered complete

Specs must be translated into tests before or alongside implementation. Required coverage:

### Unit tests

- eToro auth headers are built correctly and secrets are redacted from logs/persistence.
- `x-request-id` is generated once per submission attempt and persisted for idempotency.
- symbol resolution maps ticker to eToro `instrumentId` and caches successful lookups with instrument metadata.
- unsupported/missing/ambiguous instruments are skipped with auditable errors.
- live v1 skips shorts, non-allowlisted symbols, missing levels, leverage above 1, unavailable snapshots, stale validation, missing permission scopes, ambiguous product type, invalid market session, and price outside entry tolerance.
- eToro order payload uses amount sizing, `leverage: 1`, fixed stop loss, and take profit.
- broker rejection persists request/response and does not retry unprotected.
- ambiguous submit/close/cancel response activates the eToro broker-account circuit breaker.
- eToro trade-history rows map to win/loss/P&L lifecycle states correctly.
- contradictory reconciliation evidence maps to `needs_review`.
- untracked eToro positions/orders block new live submissions.
- eToro daily and total drawdown limits block live submissions when equity falls beyond configured thresholds.
- missing or stale eToro equity evidence blocks live submissions.
- Alpaca paper remains available only as explicit legacy adapter fallback; default execution, startup bootstrap, and Execution & Risk UI must be eToro demo oriented.

### Service/integration tests with fake eToro client

- read-only credential validation flow.
- real-trading permission validation blocks live submission when missing.
- demo order submit -> lookup -> open -> close/history lifecycle.
- live disabled path persists skipped rows and sends no broker request.
- live enabled but halted path persists risk skip and sends no broker request.
- live enabled + allowlisted + clean account path submits exactly one order for the eToro broker account.
- live enabled together with Alpaca paper creates independent candidates and does not cross-apply risk limits.
- duplicate plan/run submission does not create duplicate eToro orders.
- manual cancel only targets pending eToro orders and requires confirmation semantics.
- manual close marks position `closing` only after accepted eToro response.
- ambiguous manual close response sets `needs_review`/circuit breaker and does not duplicate close.
- rejected close keeps existing lifecycle state and records the error.

### API/UI tests

- settings expose eToro fields and never expose keys.
- Execution & Risk page shows eToro live badges and blocked-state reasons.
- live resubmit/cancel/close actions require explicit confirmation.
- risk dashboard includes eToro snapshot, drawdown, per-broker risk limits, and untracked exposure details.
- run detail shows eToro broker-order and broker-position records.

### End-to-end/sandbox validation

Before any real-money enablement in production:

1. Validate credentials against eToro read-only endpoints.
2. Resolve at least one allowlisted symbol.
3. Validate instrument metadata and price/market-session checks for at least one allowlisted symbol.
4. Submit and close at least one eToro demo order using the app.
5. Reconcile the demo order through lookup, portfolio, and trade-history evidence.
6. Verify global and eToro-account kill switches block eToro submissions.
7. Verify max drawdown protection blocks eToro submissions using controlled fake/sandbox equity snapshots.
8. Verify untracked exposure detection blocks eToro submissions using a controlled fake/sandbox snapshot.
9. Verify ambiguous live-submit simulation triggers circuit breaker and no automatic retry.
10. Record the validation artifact in the app or deployment notes.
11. Run `scripts/check_etoro_release_readiness.py`; for a real release it must fail closed unless read-only, demo lifecycle, and live-shadow artifact ids are provided. Use `--report-output` to preserve the release-readiness JSON artifact with validation command results, explicit remaining gates, and live micro-size defaults. The release checklist includes `scripts/check_broker_migration_backfill.py` and broker-account assertions inside `scripts/check_postgres_validation.py` to verify broker-account migration/backfill state before live rollout.

## Rollout phases

1. **Spec and tests:** this document plus failing tests for all safety gates.
2. **Broker adapter:** introduce broker-account abstraction without changing Alpaca paper behavior and with tests for multi-broker fan-out.
3. **eToro read-only:** credentials, instrument lookup, portfolio snapshots, risk dashboard evidence.
4. **eToro demo:** demo submit/cancel/close/reconcile only.
5. **Live shadow:** live account snapshots and would-submit audit rows, but no live submit.
6. **Live micro-size:** live submit enabled for allowlisted symbols with `$25` default cap and manual review.
7. **Measured expansion:** raise caps or add instruments only after broker-backed outcomes and incident-free operation justify it.

## Current behavior and target gates

Canonical current behavior includes the eToro integration contract, broker-account adapter abstraction, per-broker eToro risk/drawdown settings, account-scoped credential storage and redaction, read-only client wiring, demo lifecycle plumbing covered with test doubles, fail-closed live adapter behavior, live-shadow would-submit audit rows, broker-account risk/circuit-breaker integration, order-submission safety gates, broker-aware UI/API safety indicators, and release-readiness report support.

Still target/gated:

- re-read current eToro docs and confirm official demo endpoint paths before external demo mutation
- validate read-only credentials, instrument metadata, demo lifecycle, and live-shadow against external eToro evidence
- implement/enable real eToro live mutation; current live adapter returns `etoro_live_mutation_disabled`
- production rollout artifact showing release-readiness script pass with required external evidence
