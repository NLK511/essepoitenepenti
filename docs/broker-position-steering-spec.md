# Broker position steering system

**Status:** current + target behavior

Binding reference for steering app-owned broker orders/positions after submission or fill.

## Product goal

Steering is a conservative post-submit/post-fill control loop. It may:
- cancel stale pending orders
- cancel pending orders whose original rationale is clearly invalidated
- tighten or preserve filled-position exits
- lower take-profit or close exposure when evidence is clearly broken and safety checks pass

It must not replace plan generation, broker reconciliation, pre-trade risk management, or open new risk.

## Current behavior and target

Current behavior:
- app-submitted broker records, lifecycle, reconciliation, risk checks, outcomes, steering settings, decisions, and observability exist
- steering can run manually or by job path
- dry-run decisions are persisted and visible
- expired pending-order cancellation can execute live when steering is enabled and not dry-run
- invalidated pending cancellations, non-risk-increasing stop amendments, TP lowering, and close-now require dry-run sample thresholds and broker safety validation
- decisions include correlation metadata

Target behavior:
- autonomous stale/invalidated pending cancellation
- autonomous non-risk-increasing exit amendments
- safe close-now on severe invalidation
- discovery must not miss active broker exposure because of paging/age limits
- ambiguous/missing direction or reconciliation evidence produces `manual_review_required`

Invariant: steering remains app-owned only, conservative, direction-aware, and safe-side on missing evidence.

## Scope

Allowed v1 actions:
- `cancel_pending_order`
- `keep_pending_order`
- `tighten_stop_loss`
- `move_stop_to_breakeven_or_profit`
- `lower_take_profit`
- `close_position_now`
- `keep_position_exits`
- `manual_review_required`

Out of scope:
- new positions, adding size, averaging down, widening stops/loss budgets
- default target expansion or discretionary liquidation outside severe invalidation
- steering broker/manual positions not created by this app

Long and short paths are both supported and must be tested before live mutation.

## Core safety rules

Steering may make a plan more conservative; it must never make it riskier.

For long positions:
- stop-loss may only move up
- take-profit may only move down or stay unchanged by default
- lowered TP must remain above current tradable price unless manual review/close-now applies

For short positions, invert the direction:
- stop-loss may only move down
- take-profit may only move up or stay unchanged by default

Immediate close is allowed only by the severe-invalidation rule. If direction, ownership, side, quantity, or broker state is ambiguous, emit `manual_review_required` and do not mutate the broker.

`closing` broker positions remain active exposure until broker fill/reconciliation confirms closure. Do not submit duplicate close mutations for already-closing positions.

## Inputs and evidence

The steering state per app-owned broker record includes:
- plan id, ticker, intended direction, entry/stop/take-profit, horizon/expiration, rationale
- broker order/position status, quantity, side, average entry, current exits
- current price or latest stored daily close proxy
- volatility proxy when available
- latest ticker analysis/news/market-intelligence evidence
- calibrated confidence/actionability when available
- reconciliation verdict for the specific app-owned record

Missing analysis/news/price must reduce confidence or force manual review where needed, but missing news alone must not cancel/amend.

### `BrokerSteeringEvidence`

Runtime steering builds a compact evidence payload from the latest plan/signal payloads and compatible embedded fields. A legacy `steering_evidence` payload may be read as fallback.

Fields may include:
- `computed_at`
- `warnings`
- `market_intelligence_conflict_flags`
- `actionability`
- `calibrated_confidence_percent`
- `analysis_direction`
- `freshness_status`

Evidence older than one day, explicitly stale, or missing `computed_at` must not trigger live thesis invalidation by itself. Fresh ticker-specific warnings or market-intelligence conflicts may produce severe invalidation reasons. Missing/stale evidence blocks thesis-invalidation live mutations but does not block safe expired-pending cancellation.

## Decision output

Every evaluation persists a structured decision with:
- decision, ticker, plan id, broker order/position id
- reason codes and human summary
- current price/SL/TP and proposed SL/TP
- risk delta when computable
- steering confidence
- `execute_allowed`, `requires_manual_review`
- diagnostics for replay/debugging

Persist the decision whether or not any broker mutation executes.

## Pending-order rules

Pending means the app submitted a broker order and no broker fill/position exists.

### P1 — cancel expired pending order

Cancel when expiration passed or horizon elapsed with no fill.

Knobs:
- `steering.pending_expiration_grace_minutes`: `5`
- `steering.cancel_expired_pending_orders_enabled`: `true`

Default: `cancel_pending_order`.

### P2 — cancel clearly invalidated pending order

Cancel only when fresh evidence strongly contradicts the original plan. At least `steering.pending_invalidation_required_signals` must be true:
- calibrated confidence below `steering.pending_min_confidence_percent`
- actionability is `no_action`
- analysis direction contradicts original direction
- severe ticker-specific news/market-intelligence event after plan creation
- price moved beyond chase limit before entry
- broker/account reconciliation is too uncertain to trust execution state

Knobs:
- `steering.pending_min_confidence_percent`: `55`
- `steering.pending_invalidation_required_signals`: `2`
- `steering.pending_price_chase_limit_percent`: `1.0`
- `steering.cancel_invalidated_pending_orders_enabled`: `true`

Default: `cancel_pending_order`.

### P3 — keep uncertain pending order

Do not cancel solely because news is missing, refresh failed, market data is stale but reconciliation is healthy, or only one weak contradiction exists.

Default: `keep_pending_order` with `insufficient_invalidation_evidence`.

## Filled-position rules

Filled means broker shows an app-owned open position or filled lifecycle tied to a position.

### F1 — never increase downside risk

For long positions proposed SL must be `>= max(current_stop_loss, original_stop_loss)`. For shorts proposed SL must be `<= min(current_stop_loss, original_stop_loss)`. If this cannot be verified, do not amend.

Default on uncertainty: `manual_review_required`.

### F2 — close on severe thesis invalidation

Close only when at least `steering.position_close_required_signals` are true:
- confidence below `steering.position_close_confidence_percent`
- actionability is `no_action`
- analysis direction strongly contradicts held side
- new severe ticker-specific event contradicts rationale
- price breaks stop/hard invalidation while broker position remains open
- reconciliation proves the app-owned position/quantity but linked exits are missing/stale

Safety constraints:
- never close if ownership, quantity, side, or reconciliation is uncertain
- never duplicate close for an already-closing position or active close/exit order
- persist decision before broker mutation
- mark local lifecycle `closing` only after accepted broker close response
- rejected/failed/canceled/expired close responses must not mark local lifecycle `closing`
- broker fill/reconciliation remains source of final P&L/outcome

Accepted close responses are 2xx responses with absent status or status in `accepted`, `submitted`, `queued`, `pending_new`, `new`, `partially_filled`, `filled`, `closed`, or `done_for_day`.

Knobs:
- `steering.close_on_severe_invalidation_enabled`: `true`
- `steering.position_close_confidence_percent`: `40`
- `steering.position_close_required_signals`: `3`

Default: `close_position_now`.

### F3 — move stop to small profit

When unrealized gain is enough, protect a small profit.

Long trigger: current price `>= entry_price * (1 + breakeven_trigger_percent/100)`. Long new SL at least `entry_price * (1 + min_profit_lock_percent/100)`. Invert for shorts.

Knobs:
- `steering.breakeven_trigger_percent`: `0.75`
- `steering.min_profit_lock_percent`: `0.10`
- `steering.move_to_profit_enabled`: `true`

Default: `move_stop_to_breakeven_or_profit`.

### F4 — tighten stop on deterioration

If evidence worsens but is not severe enough to close, tighten SL when at least `steering.position_deterioration_required_signals` are true:
- confidence below `steering.position_min_hold_confidence_percent`
- actionability is `no_action`
- severe event contradicts rationale
- price breaks key support/momentum condition
- volatility makes original geometry stale

Long proposed SL is the highest safe value among current SL, original SL, profit lock if active, and `current_price * (1 - deterioration_stop_cushion_percent/100)`. Invert for shorts.

Knobs:
- `steering.position_min_hold_confidence_percent`: `50`
- `steering.position_deterioration_required_signals`: `2`
- `steering.deterioration_stop_cushion_percent`: `0.35`
- `steering.tighten_on_deterioration_enabled`: `true`

Default: `tighten_stop_loss`.

### F5 — lower take-profit on weakness

When the position is profitable but evidence weakens, prefer a nearer target if broker amendment is safe.

Long TP lowering requires current price above entry, proposed TP above current price by at least `steering.min_tp_distance_percent`, proposed TP below current TP, positive expected result if filled, and F4 deterioration evidence. Invert for shorts.

Long proposed TP: `current_price * (1 + weakened_thesis_tp_cushion_percent/100)`. Invert for shorts.

Knobs:
- `steering.lower_tp_on_weakness_enabled`: `true`
- `steering.weakened_thesis_tp_cushion_percent`: `0.50`
- `steering.min_tp_distance_percent`: `0.10`

Default: `lower_take_profit`; if amendment cannot be proven safe, `manual_review_required`.

### F6/F7 — stable or uncertain

Stable evidence with no profit trigger keeps exits. Broker drift, missing linked orders, ambiguous quantity, or unknown order ids block live amendments.

Defaults: `keep_position_exits` or `manual_review_required`.

## Decision priority

Evaluate in order:
1. broker/reconciliation safety
2. pending expiration
3. pending invalidation
4. filled non-risk-increase guard
5. severe close-now
6. profit-lock stop move
7. deterioration stop tightening
8. weakened-thesis TP lowering
9. keep/no-op

If both SL and TP amendments are valid, submit together only if broker support is validated; otherwise prioritize stop tightening.

## Settings defaults

All knobs use `steering.*`:
- `enabled`: `false`
- `dry_run`: `true`
- action toggles: `cancel_expired_pending_orders_enabled`, `cancel_invalidated_pending_orders_enabled`, `move_to_profit_enabled`, `close_on_severe_invalidation_enabled`, `tighten_on_deterioration_enabled`, `lower_tp_on_weakness_enabled` all default `true`
- pending defaults: grace `5`, min confidence `55`, required signals `2`, chase limit `1.0`
- filled defaults: breakeven trigger `0.75`, min profit lock `0.10`, close confidence `40`, close required signals `3`, hold confidence `50`, deterioration required signals `2`, deterioration cushion `0.35`, weakened TP cushion `0.50`, min TP distance `0.10`
- dry-run thresholds: `min_reviewed_dry_run_decisions_before_enable=30`, `min_reviewed_dry_run_amendments_before_enable=10`, `min_reviewed_dry_run_close_now_before_enable=10`

`enabled=false` prevents autonomous broker mutation. `dry_run=true` persists decisions without broker calls. Threshold names use historical `reviewed` wording but currently count persisted dry-run decisions.

## Architecture and persistence

Components:
- `BrokerSteeringStateBuilder`: loads app-owned broker/order/position/plan/evidence/price state
- `BrokerSteeringEngine`: pure deterministic rules
- `BrokerSteeringExecutor`: applies approved Alpaca mutations only when enabled and not dry-run
- `BrokerSteeringDecisionRepository`: persists audits
- scheduled/manual job: evaluates open app-owned broker records

Decision ledger fields include ids, created/executed timestamps, plan/order/position/ticker, decision, `execute_allowed`, per-decision execution status (`dry_run`, `submitted`, `succeeded`, `failed`, `blocked`), run-level execution status (`dry_run`, `no_action`, `blocked`, `partial_success`, `succeeded`, `failed`), reasons, before/after levels, risk delta, diagnostics, and error.

Run-level status is aggregated after execution and must not say `submitted` if every live decision was blocked.

## Broker execution safety

Before any live mutation:
- reload broker state
- verify app-owned ids, quantity, side, and lifecycle
- verify amendments remain non-risk-increasing
- verify market/broker accepts the action
- persist attempt/result

Broker amendment method must be validated for Alpaca. If direct replace vs cancel/replace semantics are uncertain, stay in dry-run.

## Operator UI and observability

Broker/operator UI must show enabled/dry-run state, latest decisions, recommended/executed cancellations/amendments/closes, manual-review cases, reason codes, before/after SL/TP, and execution results. Controls: run now, approve safe individual dry-run decision if supported, disable globally.

Steering observability events:
- `steering_run_started`
- `steering_decision_created`
- `steering_broker_mutation_attempted`
- `steering_broker_mutation_succeeded`
- `steering_broker_mutation_failed`
- `steering_run_completed`

Events include correlation id, ticker, plan id, decision, and reason codes.

## Test requirements

Cover before live mutation:
- pending expiration, invalidation, and uncertain keep
- long/short non-risk-increase math
- profit-lock, deterioration SL, TP lowering, severe close-now for long/short
- broker uncertainty and ambiguous direction manual review
- stable no-op
- decision persistence and diagnostics
- dry-run no broker calls
- executor success/failure status recording
- settings round-trip
- scheduled job only processes app-owned open/submitted records
- broker reload blocks stale decisions

## Rollout status

Implemented phases:
- dry-run steering core
- persistence/audit ledger
- settings
- state builder
- dry-run job/service
- API/UI visibility
- broker execution after dry-run evidence for approved safe actions

Captured decisions:
1. V1 supports long and short app-owned positions.
2. Severe invalidation may trigger `close_position_now`.
3. Alpaca amendment method must remain validated before live amendments.
4. TP lowering is eligible for automation after dry-run review and safety validation.
5. Autonomous amendments require dry-run evidence thresholds.
