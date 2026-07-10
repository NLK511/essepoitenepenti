# Multi-broker and eToro implementation plan

**Status:** archived implementation history

This archived record captures the multi-broker/eToro implementation history. Current broker behavior and remaining production gates live in `../../specs/multi-broker-execution-risk-spec.md`, `../../specs/etoro-live-trading-integration-spec.md`, and `../../production-readiness-plan.md`.

## Implementation progress

- [x] Phase 0 spec/API reconfirmation plan documented; no eToro client calls implemented yet.
- [x] Phase 1 first batch: broker-account persistence model, repository, account-scoped credential storage, default Alpaca paper account bootstrap helper, broker-order `broker_account_id`, and global live cap settings helpers.
- [x] Phase 1 remaining: local Docker Postgres validation environment created and `scripts/check_postgres_validation.py` passed upgrade/schema/default-account smoke validation with `POSTGRES_TEST_DATABASE_URL`. Data-dependent historical recomputation tests remain opt-in for restored databases via `POSTGRES_VALIDATION_INCLUDE_DATA_TESTS=1`.
- [x] Phase 1 migration/backfill smoke: added broker-account migration validation script covering Alembic upgrade-to-head, broker account/safety tables, account-scoped columns, and default Alpaca paper account backfill.
- [x] Phase 1 Postgres validation wiring: `scripts/check_postgres_validation.py` now verifies broker-account tables, account-scoped columns, safety tables, and default Alpaca paper account after Postgres upgrade.
- [x] Phase 1 route/API exposure and startup bootstrap: broker-account APIs are available and app startup now idempotently ensures the default Alpaca paper broker account.
- [x] Phase 2 first batch: broker adapter protocol/result dataclasses, fake adapter contract tests, redaction helper, and Alpaca paper adapter wrapper/regression tests.
- [x] Phase 2 second batch: `OrderExecutionService` can submit/cancel/refresh/close through a broker adapter while preserving Alpaca paper client behavior and tests.
- [x] Phase 2 third batch: explicit broker adapter factory, account-scoped Alpaca adapter construction, legacy config fallback, and adapter-backed live snapshot collection.
- [x] Phase 2 remaining: broker-neutral amend-position-protection contract is specified in the adapter protocol; Alpaca paper bracket amend now uses the adapter path after broker lookup validation.
- [x] Phase 3 first batch: multi-broker fan-out service, one persisted candidate per enabled broker account, per-account autonomous/halt gates, global halt gate, per-account adapter submit, and duplicate run/plan/account de-dupe.
- [x] Phase 3 second batch: per-account symbol allowlist/denylist, position notional, open position, open notional, same-ticker, daily order-count gates, plus global live notional and daily order-count caps.
- [x] Phase 4 first batch: broker-account drawdown baseline state, drawdown warm-up block for live accounts, circuit-breaker persistence, circuit-breaker blocks, and ambiguous submit -> `needs_review` plus circuit breaker.
- [x] Phase 4 second batch: drawdown USD/pct gates, high-water persistence tests, rate-limit submit -> circuit breaker, manual circuit-breaker clear requiring reason and optional trusted drawdown state, and account-isolated circuit breaker tests.
- [x] Phase 4 third batch: multi-account reconciliation helper keyed by `broker_account_id`, contradictory missing broker evidence -> `needs_review`, and partial-close handling that keeps remaining exposure open.
- [x] Phase 5 first batch: eToro read-only HTTP client, read-only adapter, auth headers/request ids, permission/rate-limit error mapping, portfolio/history readers, instrument metadata cache, secret redaction tests, and adapter-factory eToro read-only wiring.
- [x] Phase 6 first batch: eToro demo adapter order construction and mocked demo submit/lookup/cancel/close lifecycle calls, with safe rejection for unsupported short/leveraged/unprotected requests and ambiguous timeout handling.
- [x] Phase 7 first batch: server-side eToro live-account gates for live trading enablement, operator acknowledgement, demo-validation artifact/override, real-trading permission evidence, and live shadow would-submit audit rows that skip mutation calls.
- [x] Phase 7 second batch: eToro live latest-price/entry-zone slippage gate with missing-price and outside-tolerance blocks before any mutation path.
- [x] Phase 8 first batch: broker-account API visibility for account list/detail, redacted validation/risk settings, live/demo/paper badges, drawdown state, circuit breakers, and server-side circuit-breaker clear requiring a reason.
- [x] Phase 8 second batch: broker-account API controls for account halt, labels, allowlist/denylist, notional/open-position caps, and live risk-setting updates with redacted responses.
- [x] Phase 8 third batch: server-side eToro live manual action confirmation for broker-order resubmit/cancel, including manual-actions kill switch enforcement and exact confirmation text.
- [x] Phase 9 first batch: eToro release-readiness validation script with fail-closed external artifact checks, default/focused/migration/Postgres/frontend validation commands, dry-run support, and operator docs.
- [x] Phase 9 second batch: release-readiness JSON report output with artifact ids, validation command results, missing-artifact status, and live micro-size defaults.
- [x] Phase 8 fourth batch: broker risk API for global live caps and aggregate live-account risk summary, with round-trip update coverage.
- [x] Phase 4 fourth batch: multi-account reconciliation now activates broker-account circuit breakers on stale snapshots and contradictory/missing broker evidence that marks positions `needs_review`.
- [x] Phase 8 fifth batch: broker workbench payload now includes redacted broker accounts, live/demo/paper badges, credential presence, drawdown/circuit-breaker state, global live caps, and aggregate live-account usage.
- [x] Phase 8 sixth batch: broker order and broker position APIs now filter by broker account, broker, account mode, status, and run id for operator live/demo/paper separation.
- [x] Phase 8 seventh batch: Execution & Risk frontend now displays broker-account live/demo/paper badges, credential/drawdown/circuit-breaker status, global live caps/usage, broker-account ids on orders, and exact eToro live manual-action confirmation prompts.
- [x] Phase 8 eighth batch: broker workbench backend and Execution & Risk frontend now support broker-account, broker, account-mode, and status filters for live/demo/paper separation.
- [x] Phase 7 third batch: eToro live adapter is explicitly fail-closed for submit/cancel/close, advertises live mode with mutations disabled, and factory routes live eToro accounts to this disabled adapter.
- [x] Phase 8 ninth batch: broker-account API can record demo-validation artifacts into live-gate risk settings with timestamped evidence and validation.
- [x] Phase 8 tenth batch: Execution & Risk frontend broker-account cards can record eToro demo-validation artifacts and clear active broker-account circuit breakers with operator reasons.
- [x] Phase 8 eleventh batch: broker-position close API requires exact eToro live confirmation, respects manual-actions kill switch, and remains fail-closed with `etoro_live_mutation_disabled` for real-money close.

This plan translates `multi-broker-execution-risk-spec.md` and `etoro-live-trading-integration-spec.md` into an ordered, test-first delivery path.

## Aurelio dev protocol

- Specs are the source of truth. If implementation discovers a conflict, update the relevant spec before code.
- Every implementation phase starts by adding or updating failing tests that encode the spec behavior.
- Alpaca paper behavior must remain unchanged unless a spec explicitly says otherwise.
- Real-money eToro live submission stays disabled until all prior phases pass, demo validation artifacts exist, and operator live gates are server-enforced.
- Any ambiguous live broker state blocks autonomous submission and creates review evidence.
- After each completed phase: run targeted tests, run the broker/risk regression suite, update docs/checklists, commit.

## Target order

1. Multi-broker account model and persistence.
2. Broker adapter contract and Alpaca migration behind it.
3. Multi-broker fan-out and risk gates.
4. Reconciliation/circuit-breaker/drawdown foundation.
5. eToro read-only and metadata validation.
6. eToro demo execution lifecycle.
7. eToro live safety gates and shadow mode.
8. UI/API visibility and operator controls.
9. Release validation and live micro-size readiness.

## Phase 0 — Reconfirm specs and eToro API facts

Purpose: avoid implementing against stale broker semantics.

Tasks:
- Re-read current eToro Developer Portal before coding eToro client calls.
- Update `etoro-live-trading-integration-spec.md` if endpoint paths, payload fields, auth headers, demo endpoint paths, permissions, or product metadata semantics differ.
- Record demo-vs-real endpoint mapping in the spec before client implementation.
- Confirm whether `closed_flat` needs a schema migration or maps to `needs_review` for v1.

Tests to prepare:
- No code behavior yet; add a spec-review checklist entry to the implementation PR/commit notes.

Acceptance:
- Specs still describe the implementation target precisely.
- Any API-doc discrepancy is resolved in docs before code.

## Phase 1 — Broker-account schema and settings

Purpose: introduce durable broker-account identity without changing current Alpaca paper behavior.

Implementation tasks:
- Add persistence for broker accounts, credential references, validation state, per-account halt state, and per-account risk settings.
- Add immutable `broker_account_id` to broker-order, broker-position, reconciliation snapshot, steering decision, and halt/circuit-breaker records where applicable.
- Preserve existing `broker` and `account_mode` fields for compatibility during migration.
- Add a migration that creates one default Alpaca paper broker account for existing deployments.
- Add unique protection for broker-order candidates using `(run_id, recommendation_plan_id, broker_account_id)` or the closest existing plan id field, plus existing client-order uniqueness.
- Add settings serializers/deserializers for global risk caps and `broker_accounts`.
- Ensure credential references are scoped by broker account, not provider name.

Required tests first:
- `tests/test_broker_accounts.py`
  - creates default Alpaca paper account on migration/bootstrap.
  - `broker_account_id` is immutable while `account_label` can change.
  - credentials are attached to account id, not broker name.
  - disabled account is visible but not selected for fan-out.
- `tests/test_migrations.py`
  - migration upgrades from current schema and backfills existing broker records safely.
  - uniqueness exists for `(run_id, recommendation_plan_id, broker_account_id)`.
- `tests/test_settings_api.py`
  - broker accounts can be listed/updated with secret references redacted.
  - global aggregate live caps round-trip.

Acceptance:
- Current Alpaca paper tests still pass.
- Existing broker-order and broker-position UI/API payloads remain backward compatible while including `broker_account_id` when available.

## Phase 2 — Broker adapter contract

Purpose: make Alpaca and eToro interchangeable execution targets while exposing broker capabilities.

Implementation tasks:
- Define a broker adapter protocol/interface in `services/brokers/` or equivalent.
- Adapter methods:
  - `validate_credentials`
  - `get_capabilities`
  - `resolve_instrument`
  - `get_account_snapshot`
  - `get_open_orders`
  - `get_open_positions`
  - `submit_order`
  - `lookup_order`
  - `cancel_order`
  - `close_position`
  - `get_trade_history`
- Define normalized request/response dataclasses for submit, cancel, close, lookup, snapshot, instrument metadata, and lifecycle evidence.
- Include capability metadata: supported actions, order types, leverage bounds, short support, min/max notional, protective-order support, market-hours behavior, idempotency behavior.
- Migrate Alpaca paper behind the adapter with no behavior change.

Required tests first:
- `tests/test_broker_adapter_contract.py`
  - fake adapter contract covers open, lookup, cancel, close, history, snapshot, capabilities.
  - ambiguous adapter result is represented explicitly, never as success.
  - secrets do not appear in normalized response repr/json.
- `tests/test_alpaca_adapter_regression.py`
  - Alpaca order payloads remain equivalent to current behavior.
  - Alpaca cancel/resubmit/position lifecycle tests still pass.

Acceptance:
- Existing `test_order_execution.py`, broker lifecycle, broker steering, and reconciliation tests pass through the adapter path.

## Phase 3 — Multi-broker fan-out and risk engine

Purpose: evaluate one candidate per enabled broker account with independent and global risk controls.

Implementation tasks:
- Replace/wrap single broker selection with enabled broker-account fan-out.
- Persist skipped candidates with explicit reason codes.
- Enforce per-account gates: enabled, autonomous enabled, account halt, symbol allowlist/denylist, action support, order count, notional caps, exposure caps, drawdown, stale snapshots, untracked exposure.
- Enforce global gates: global execution switch, global halt, aggregate live open notional, aggregate live drawdown, aggregate live order count.
- Make candidate creation transactional and duplicate-safe under concurrent workers.
- Add risk-decision evidence payload with snapshot ids, equity inputs, exposure inputs, open-order inputs, and correlation ids.

Required tests first:
- `tests/test_multi_broker_fanout.py`
  - one plan creates one candidate per enabled broker account.
  - one broker halt does not block another broker.
  - global halt blocks all accounts.
  - duplicate concurrent candidate creation does not produce duplicate submits.
- `tests/test_multi_broker_risk.py`
  - per-account notional/exposure/order-count limits block correctly.
  - global aggregate caps block correctly.
  - missing/stale/contradictory snapshot blocks live account only.
  - untracked live exposure blocks when configured.
  - mutable label changes do not affect duplicate detection or reconciliation.

Acceptance:
- Alpaca paper can be enabled as one broker account and behaves as before.
- Multiple accounts produce independent auditable outcomes.

## Phase 4 — Drawdown, reconciliation, and circuit breakers

Purpose: make unknown state safe before any eToro mutation exists.

Implementation tasks:
- Add per-account drawdown state with broker timezone, daily boundary, current equity, daily high-water, total high-water, baseline source, freshness, and trust flag.
- Implement drawdown warm-up block for live accounts with no trusted baseline.
- Add per-account circuit-breaker state and events.
- Trigger circuit breaker on repeated adapter failures, rate limits, stale/contradictory snapshots, unknown submit/cancel/close outcome, credential validation failure, and reconciliation uncertainty.
- Add manual server-side clear path requiring operator, reason, and latest trusted snapshot where applicable.
- Extend reconciliation snapshots with account id and raw redacted payload metadata.

Required tests first:
- `tests/test_broker_drawdown_state.py`
  - warm-up blocks live submission.
  - high-water marks persist across restart.
  - daily boundary uses broker timezone and persisted boundary.
  - daily and total drawdown USD/pct block.
- `tests/test_broker_circuit_breaker.py`
  - unknown submit result sets `needs_review` and circuit breaker.
  - rate-limit blocks further autonomous submissions.
  - manual clear requires reason and preserves audit history.
  - one account's circuit breaker does not block another account.
- `tests/test_broker_reconciliation_multi_account.py`
  - reconciles by `broker_account_id`.
  - contradictory broker evidence marks `needs_review`.
  - partial fill/partial close leaves remaining exposure active.

Acceptance:
- Autonomous live candidates cannot pass without trusted snapshot and drawdown state.

## Phase 5 — eToro read-only client and secret safety

Purpose: connect to eToro without placing orders.

Implementation tasks:
- Implement eToro HTTP client with auth headers, `x-request-id`, bounded timeout, structured error mapping, and retry rules for safe read-only calls only.
- Implement credential validation and permission/scope detection.
- Implement market-data search/instrument resolution with metadata cache.
- Implement portfolio, P&L, open orders/positions, and trade-history readers.
- Implement redaction for headers, nested payloads, logs, observability events, UI responses, and test snapshots.
- Add eToro adapter read-only methods.

Required tests first:
- `tests/test_etoro_client_readonly.py`
  - sends required headers and unique request id.
  - maps 401/403 to permission/credential errors.
  - maps 429 and retry-after to rate-limit circuit-breaker signal.
  - parses portfolio/P&L/history fixtures.
- `tests/test_etoro_instrument_metadata.py`
  - resolves allowed symbol to instrument id and metadata.
  - ambiguous CFD/underlying mapping blocks.
  - unsupported market/currency/session/min size/protective constraints block.
  - cache invalidation/freshness works.
- `tests/test_etoro_secret_redaction.py`
  - `x-user-key` never appears in persisted payloads, logs, observability, UI JSON, exceptions, or snapshots.
- `tests/test_etoro_permissions.py`
  - read-only/demo-only/expired/revoked/missing-real-trading permissions block live.

Acceptance:
- eToro account can be validated and reconciled read-only.
- No mutation endpoint is callable from autonomous execution yet.

## Phase 6 — eToro demo execution lifecycle

Purpose: prove open/lookup/cancel/close/reconcile behavior without real money.

Implementation tasks:
- Implement demo endpoint mapping separately from real endpoint mapping.
- Implement eToro order construction for long-only market buys with leverage 1, USD amount, fixed stop loss, and take profit.
- Implement demo submit with idempotent `x-request-id` persisted before the HTTP call.
- Implement lookup, cancel pending order, close open position, portfolio reconciliation, P&L/trade-history reconciliation.
- Implement partial-fill/partial-close lifecycle handling.
- Record demo validation artifact required by live gate.

Required tests first:
- `tests/test_etoro_demo_execution.py`
  - constructs correct order payload for valid long plan.
  - skips shorts, missing levels, non-allowlisted symbols, leverage > 1, stale metadata, stale snapshot.
  - broker rejection persists request/response and does not retry unprotected.
  - timeout/ambiguous submit sets `needs_review` and circuit breaker.
  - lookup lag keeps submitted state but blocks duplicate submit.
  - cancel pending demo order maps to canceled.
  - close open demo position maps to closing then win/loss/flat/needs_review from history.
  - partial close keeps remaining exposure open.

Acceptance:
- At least one controlled demo lifecycle can be run manually in a non-test environment and produces a validation artifact.

## Phase 7 — eToro live gates and shadow mode

Purpose: make live readiness server-enforced before allowing real money.

Implementation tasks:
- Add live broker-account settings with conservative defaults: disabled, autonomous disabled, manual live disabled until acknowledged, notional cap `$25`, empty allowlist, leverage 1, daily order count 1, block on untracked exposure.
- Add live acknowledgement and demo-validation prerequisite enforcement.
- Add live shadow/would-submit mode: construct and risk-evaluate live candidates without calling mutation endpoints.
- Add latest-price/entry-zone slippage check.
- Enable real submit/cancel/close methods only behind all gates.
- Ensure demo-validation override only bypasses demo prerequisite, not any other safety gate.

Required tests first:
- `tests/test_etoro_live_gates.py`
  - live defaults block all real submissions.
  - enabled account without `live_trading_enabled` blocks.
  - missing live acknowledgement blocks.
  - missing demo validation blocks unless documented override exists.
  - override does not bypass permission, allowlist, drawdown baseline, risk, protective stops, untracked exposure, or circuit breaker.
  - price outside entry tolerance skips.
  - real-trading permission missing skips with `etoro_permission_missing`.
- `tests/test_etoro_live_shadow.py`
  - shadow mode persists would-submit audit rows with payload redacted.
  - shadow mode never calls mutation endpoints.

Acceptance:
- Live mutation code exists but cannot run unless every server-side gate passes.
- Shadow mode can run against live read-only snapshots.

## Phase 8 — UI/API operator controls

Purpose: make multi-broker and live-money state impossible to miss.

Implementation tasks:
- Extend Broker Orders / Execution & Risk APIs with broker accounts, account labels, account modes, live badges, risk states, drawdown, circuit breakers, validation state, untracked exposure, and global aggregate risk.
- Add filters by broker account, broker, account mode, status, and live/demo/paper.
- Add explicit confirmation dialogs for live manual resubmit/cancel/close; enforce confirmation server-side.
- Add controls for broker-account halt, global halt, circuit-breaker clear, live acknowledgement, allowlist, notional/order caps, and demo-validation artifact display.
- Ensure UI never displays secrets or raw unredacted headers.

Required tests first:
- Backend:
  - `tests/test_broker_accounts_api.py`
  - `tests/test_broker_risk_api_multi_account.py`
  - `tests/test_etoro_live_manual_actions_api.py`
- Frontend:
  - add/extend Vitest tests for live badges, filters, confirmation flows, redaction, and circuit-breaker display.

Acceptance:
- Operator can understand why every candidate submitted/skipped/blocked.
- Manual live mutation cannot be invoked without explicit server-side confirmation.

## Phase 9 — Release validation and rollout gates

Purpose: prevent accidental real-money launch.

Implementation tasks:
- Add release checklist script or documented command sequence.
- Run default unit suite.
- Run broker/risk focused suite.
- Run migration upgrade-to-head validation, including Postgres path where available.
- Run frontend tests.
- Run eToro read-only validation in target environment.
- Run eToro demo open/close lifecycle and record artifact.
- Run live shadow mode for at least one market session with no mutation endpoint calls.
- Only then enable live micro-size with `$25` cap and daily order count 1.

Required tests/validation:
- `pytest tests/test_broker_accounts.py tests/test_broker_adapter_contract.py tests/test_multi_broker_fanout.py tests/test_multi_broker_risk.py tests/test_broker_drawdown_state.py tests/test_broker_circuit_breaker.py tests/test_etoro_*.py`
- Existing broker regression suite.
- Migration tests and Postgres smoke if configured.
- Frontend test suite.

Acceptance:
- Release notes include demo validation artifact id, live shadow evidence, active broker accounts, caps, allowlist, drawdown baseline, and kill-switch state.

## Work breakdown by likely code area

- Persistence:
  - `src/trade_proposer_app/persistence/models.py`
  - `alembic/versions/*`
  - repositories for broker accounts, drawdown state, circuit breakers, credential refs.
- Services:
  - new broker adapter package.
  - `services/order_execution.py`
  - `services/risk_management.py`
  - `services/broker_reconciliation.py`
  - `services/broker_position_steering*.py`
  - new eToro client/adapter services.
- APIs:
  - `src/trade_proposer_app/api/router.py` or extracted broker routes.
  - settings and broker workbench endpoints.
- Frontend:
  - broker order/workbench pages.
  - execution/risk dashboard components.
  - settings/account management controls.
- Tests:
  - add focused unit tests before each code phase.
  - keep existing Alpaca tests as regression tests.

## Non-goals for this implementation wave

- Short eToro trading.
- Leveraged/CFD trading.
- Copy trading or portfolio products.
- Automatic liquidation on halt.
- Broad cancel-all on halt.
- Position scaling/pyramiding.
- Trusting simulated outcomes over broker evidence.

## Done definition

The implementation is complete only when:

- Specs, tests, and code agree.
- Alpaca paper behavior is preserved.
- Multiple broker accounts can be enabled independently.
- Per-account and global live risk gates are server-enforced.
- eToro read-only, demo, and live-shadow paths are validated.
- Real eToro mutation endpoints are covered by tests for submit, lookup, cancel, close, reconciliation, drawdown, rate-limit, unknown outcome, and secret redaction.
- UI/API clearly shows live risk state and requires server-enforced confirmation for manual live actions.
- Release validation artifacts are recorded before any live micro-size trade.
