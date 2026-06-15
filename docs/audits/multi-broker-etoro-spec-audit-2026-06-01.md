# Multi-broker and eToro live trading spec audit — 2026-06-01

**Status:** active audit record

## Scope

Audited target specs for adding eToro live trading and multi-broker execution:

- `docs/multi-broker-execution-risk-spec.md`
- `docs/etoro-live-trading-integration-spec.md`
- Current-context references:
  - `docs/broker-risk-management-spec.md`
  - `docs/broker-position-lifecycle-spec.md`
  - `docs/broker-position-steering-spec.md`

Goal: identify blind spots that could allow unsafe real-money behavior, ambiguous implementation, weak testing, or poor operator auditability.

## Executive conclusion

The previous specs captured the broad direction correctly: eToro must be broker-account based, default-off, demo-first, allowlisted, audited, and risk-gated.

However, several live-trading blind spots needed hardening before implementation:

1. Durable broker-account identity was not explicit enough.
2. Duplicate protection did not address concurrent workers.
3. Per-broker risk existed, but aggregate live exposure/drawdown was not specified.
4. Drawdown rules missed baseline/warm-up behavior.
5. API failure, timeout, rate-limit, and unknown accepted-state behavior were underspecified.
6. eToro instrument ambiguity, CFD-vs-underlying mapping, market hours, minimum sizes, and protective-order constraints were not strict enough.
7. Credential scope/permission validation was not explicit enough.
8. Secret redaction was not tested deeply enough.
9. Lifecycle rules did not emphasize partial fills/partial closes enough for live accounts.
10. Main API-call tests needed explicit circuit-breaker and max-drawdown cases.
11. Demo-validation override semantics needed tighter limits.

The specs were hardened in this audit pass.

## Findings and remediation

### A1 — Broker account identity must be immutable

**Risk:** Using `(broker, account_mode, account_label)` for duplicate protection or joins is unsafe because labels can change. A label rename could break historical audit or duplicate detection.

**Remediation added:** `multi-broker-execution-risk-spec.md` now requires immutable `broker_account_id` for persistence, duplicate protection, risk state, and audit joins. `account_label` is display-only.

### A2 — Concurrent worker duplicate live submissions

**Risk:** Existing fan-out rules did not explicitly require transactional uniqueness. Two workers could create the same live candidate and both submit.

**Remediation added:** Candidate creation and duplicate detection must be transactionally safe. Duplicate scope is now `(run_id, plan_id, broker_account_id)`. If a durable uniqueness lock cannot be acquired, the app must skip/warn rather than risk duplicate live orders.

### A3 — Global aggregate live exposure/drawdown missing

**Risk:** Per-broker limits alone can still overexpose the operator when multiple live brokers are enabled simultaneously.

**Remediation added:** Global optional aggregate live caps were specified:

- `global_max_live_open_notional_usd`
- `global_max_live_daily_drawdown_usd`
- `global_max_live_daily_drawdown_pct`
- `global_max_live_order_count_per_day`

Risk rules now block when configured global aggregate caps would be exceeded. If aggregate caps are left unset, live expansion must document why per-broker-only limits are sufficient.

### A4 — Drawdown baseline/warm-up missing

**Risk:** Without a persisted baseline/high-water mark, a restart or first run could treat drawdown as zero and permit live trading.

**Remediation added:** Live broker accounts enter drawdown warm-up when no trusted high-water baseline exists. Live autonomous submission is blocked until an initial trusted baseline is recorded. Daily boundaries must use persisted broker timezone/day boundary data.

### A5 — API timeout/unknown accepted state not safe enough

**Risk:** If a live submit/close/cancel times out, the broker may have accepted the order. Retrying with a new idempotency key can duplicate real exposure.

**Remediation added:** Specs now require broker-account circuit breakers. Unknown live submission outcome becomes `needs_review` plus circuit breaker. Open orders must not retry with a new idempotency key unless prior attempt is proven not accepted or operator explicitly performs reviewed resubmit.

### A6 — Broker rate limits and outages underspecified

**Risk:** Repeated API errors/rate-limits can lead to stale snapshots, repeated failed submits, or blind retries.

**Remediation added:** Circuit breaker triggers now include repeated failures, rate limits, stale/contradictory snapshots, failed validation, and reconciliation uncertainty. Tests must verify rate-limit recording and submission blocking.

### A7 — eToro instrument ambiguity and CFD risk

**Risk:** eToro may expose instruments where a symbol maps to CFD, underlying, crypto, or multiple products. Accidentally trading a CFD or unsupported product would violate v1 risk assumptions.

**Remediation added:** eToro live v1 blocks unless metadata proves product type, exchange/market, currency, tradability, minimum/maximum size, protective-order constraints, market hours, and non-leveraged underlying/cash behavior. Ambiguous mappings use `etoro_instrument_ambiguous`.

### A8 — eToro market order slippage and session checks

**Risk:** A market order can execute far outside the plan entry zone or outside expected trading session behavior.

**Remediation added:** eToro market orders require latest-price/slippage sanity checks when market data is available. If price is outside configured tolerance, skip with `etoro_price_outside_entry_tolerance`. Unsupported/ambiguous market session blocks live trading.

### A9 — Credential permission validation missing

**Risk:** A key may be read-only, demo-only, expired, revoked, or real-trading-disabled. The app must not infer permission from key existence.

**Remediation added:** eToro scope/permission validation is mandatory. Live trading requires real-trading permission; read-only or demo-only keys block live submissions with `etoro_permission_missing`.

### A10 — Credentials scoped too broadly

**Risk:** Storing eToro credentials only by provider could mix demo/live keys or multiple eToro accounts.

**Remediation added:** Credentials must be encrypted and scoped to broker account. Demo and live keys must be separate broker-account credentials and validated independently.

### A11 — Secret redaction not exhaustive

**Risk:** Live user keys could leak through raw payloads, logs, UI responses, snapshots, observability events, or failed test snapshots.

**Remediation added:** Persistence/audit section now requires redaction tests for nested payloads, headers, observability events, UI responses, and failure logs.

### A12 — Partial fills and partial closes

**Risk:** Treating partial close evidence as final win/loss can undercount remaining exposure or overstate performance.

**Remediation added:** eToro lifecycle rules now state that partial fills and partial closes keep remaining exposure active. A final win/loss requires closed-trade evidence for the full app-owned quantity or unresolved remainder becomes `needs_review`.

### A13 — Main API-call tests were not strict enough

**Risk:** Implementation could test happy paths only and miss max drawdown, rate limit, ambiguous responses, and multi-broker independence.

**Remediation added:** Test requirements now include unknown submission outcome, rate-limit response, global aggregate caps, drawdown warm-up, immutable broker-account id after label changes, ambiguous eToro submit/close/cancel circuit breaker, permission validation, and price/session/instrument metadata checks.

### A14 — Demo override could be misread as broad safety override

**Risk:** A documented override for missing demo validation could accidentally be implemented as a general bypass for live safety gates.

**Remediation added:** eToro spec now states that a demo-validation override may only bypass the demo-order prerequisite. It cannot bypass permission validation, live acknowledgement, allowlists, drawdown baseline, risk limits, protective stops, untracked-exposure checks, or circuit breakers.

## Remaining implementation cautions

These are not spec gaps after hardening, but implementation must pay close attention:

- eToro's current docs must be re-read immediately before coding because endpoint names and payload semantics may change.
- Demo endpoints must be mapped explicitly; do not assume real endpoint paths are reused unchanged.
- The current broker position lifecycle spec is implemented for Alpaca bracket orders. eToro lifecycle implementation must be broker-specific under the multi-broker target, not a forced reuse of Alpaca bracket assumptions.
- `closed_flat` may require schema support. Until then, flat outcomes should be `needs_review` or handled by an explicit schema migration.
- Operator confirmations for live manual actions must be server-enforced, not only UI-enforced.
- Any real-money rollout must start with live shadow/would-submit mode before live micro-size.

## Spec files hardened in this audit

- `docs/multi-broker-execution-risk-spec.md`
- `docs/etoro-live-trading-integration-spec.md`

## Audit status

- [x] blind spots identified
- [x] target specs hardened
- [ ] implementation tests written
- [ ] code implemented
- [ ] demo validation performed
- [ ] live shadow validation performed
- [ ] live micro-size validation performed
