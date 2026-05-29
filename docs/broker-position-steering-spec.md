# Broker position steering system

**Status:** current + target behavior

## Product goal

Aurelio needs a downstream steering layer after analysis, planning, and broker submission.

The steering system monitors app-submitted broker orders and broker-backed positions while the market changes. Its goal is conservative control of already-accepted exposure:

- cancel stale pending orders before they become accidental trades
- cancel pending orders when the original rationale is no longer valid
- tighten or preserve protective exits for filled positions as price/news evolves
- when evidence is unclear, prefer capital preservation and small realized profit over hoping for the original target

This is not a replacement for plan generation, broker reconciliation, or pre-trade risk management. It is a post-submit/post-fill control loop.

## Current implementation status

### Current behavior

- the app can generate recommendation plans with entry, stop-loss, take-profit, horizon, confidence, and rationale payloads
- the app can submit Alpaca paper bracket orders and persist broker order/position lifecycle records
- broker risk management blocks new submissions before they happen
- broker reconciliation tracks app-vs-broker drift and broker lifecycle status
- simulated/effective outcomes can evaluate historical plan performance
- steering dry-run decisions are persisted, exposed in settings, and can be triggered manually or by the scheduled job path
- expired pending-order cancellation can execute live when steering is enabled and dry_run is false; invalidated pending cancellations, non-risk-increasing stop amendments, take-profit lowering, and severe-invalidation close-now stay blocked until the dry-run sample thresholds are met
- steering decisions and run events include observability correlation metadata

### Target behavior

- autonomous cancellation of stale pending broker orders
- autonomous cancellation of pending orders whose rationale has decayed
- autonomous stop-loss/take-profit amendment loop for filled positions
- live broker mutation only after dry-run evidence and Alpaca safety validation
- active state discovery must not miss still-open orders or positions just because they are older than a paging limit; discovery should prioritize active broker records over historical noise
- if the plan direction is missing, unsupported, or ambiguous, the engine must emit `manual_review_required` instead of guessing long/short
- broker reconciliation health should be derived from the latest reconciliation evidence available for the app-owned broker record; missing reconciliation evidence should keep the system on the safe side

### Current + target behavior

- steering remains conservative and app-owned only
- long/short safety rules stay direction-aware
- missing evidence keeps the system on the safe side

## Scope

### In v1

The steering system acts only on broker records created by this app.

It may recommend or execute these actions:

1. `cancel_pending_order`
2. `keep_pending_order`
3. `tighten_stop_loss`
4. `move_stop_to_breakeven_or_profit`
5. `lower_take_profit`
6. `close_position_now`
7. `keep_position_exits`
8. `manual_review_required`

### Out of scope for v1

- opening new positions
- averaging down
- adding to winners
- increasing position size
- loosening stop-loss risk
- widening the original loss budget
- increasing take-profit targets by default
- discretionary market liquidation outside the explicit severe-invalidation rule
- steering broker/manual positions that were not created by this app

V1 supports both long and short app-owned positions. Direction-specific math must be tested for both sides before broker mutation is enabled.

A future version may add partial profit-taking or trend-following target expansion, but those are intentionally excluded from the first version unless separately specified and tested.

## Core principle

The steering layer is allowed to make a plan more conservative. It is not allowed to make a plan riskier.

For a long position:

- a stop-loss may only move up, never down
- take-profit may only move down or stay unchanged by default
- take-profit must remain above current tradable price unless the action is escalated to manual review or a future close-now action

For a short position, invert the direction:

- a stop-loss may only move down, never up
- take-profit may only move up or stay unchanged by default

Immediate close is allowed only by the explicit severe-invalidation rule. It is conservative because it removes exposure instead of increasing risk.

If direction-specific logic is missing or ambiguous, v1 must emit `manual_review_required` and do nothing at the broker.

## Inputs

The steering engine needs a compact state object per broker order/position:

- recommendation plan id
- ticker
- intended direction
- generated entry, stop-loss, take-profit, horizon, expiration timestamp
- current broker order status
- current broker position status
- current quantity and average entry price when filled
- current stop-loss and take-profit order levels if available
- latest tradable market price
- current implementation may use the latest stored daily market bar close as a proxy when a live quote is unavailable
- latest intraday/daily volatility proxy, preferably ATR or fallback percent move
- latest ticker analysis summary
- latest news/market-intelligence evidence summary
- latest calibrated confidence/actionability if available
- original rationale snapshot from the plan payload
- current broker reconciliation health
- a clear broker-reconciliation verdict for the specific app-owned order/position being reviewed

The engine must tolerate missing analysis/news/price fields. Missing evidence should reduce confidence in amendments and may force manual review, but missing news alone must not cancel or amend an order.

### Current evidence read model

Current implementation may read a compact `steering_evidence` payload from the latest plan/signal payload while a fuller persisted read model is still pending. The payload can include:

- `computed_at`
- `warnings`
- `market_intelligence_conflict_flags`
- `actionability`
- `calibrated_confidence_percent`
- `analysis_direction`
- `freshness_status`

Evidence older than one day, explicitly stale, or missing `computed_at` must not trigger live thesis invalidation by itself. Fresh ticker-specific warnings or market-intelligence conflicts may set severe invalidation reason codes. Plan warning strings remain only a compatibility fallback.

## Decision outputs

Every steering evaluation returns a structured decision:

- `decision`: one of the v1 action names
- `ticker`
- `recommendation_plan_id`
- `broker_order_id` and/or `broker_position_id`
- `reason_codes`
- `human_summary`
- `current_price`
- `current_stop_loss`
- `current_take_profit`
- `proposed_stop_loss`
- `proposed_take_profit`
- `risk_delta_usd` or `risk_delta_percent` when computable
- `confidence`: low/medium/high confidence in the steering decision itself
- `execute_allowed`: boolean
- `requires_manual_review`: boolean
- raw diagnostic payload for replay/debugging

The decision object is persisted whether or not a broker mutation is executed.

## Pending-order steering rules

Pending means the app submitted a broker order, but no broker position/fill exists yet.

### Rule P1: cancel expired pending order

Cancel when:

- the plan expiration timestamp has passed, or
- the generated horizon has elapsed and no fill exists

Tunable knobs:

- `steering.pending_expiration_grace_minutes`, default `5`
- `steering.cancel_expired_pending_orders_enabled`, default `true`

Default action: `cancel_pending_order`.

### Rule P2: cancel clearly invalidated pending order

Cancel when fresh evidence contradicts the original plan strongly enough that a new plan would not be actionable.

A pending order is clearly invalidated when at least two of these are true:

- current calibrated confidence is below `steering.pending_min_confidence_percent`
- current actionability says `no_action` or equivalent
- current analysis direction contradicts the original direction
- severe negative ticker-specific news or market-intelligence event appears after plan creation
- price moved beyond a chase limit before entry, making the original entry/stop/target geometry stale
- broker/account reconciliation is uncertain enough that execution state cannot be trusted

Tunable knobs:

- `steering.pending_min_confidence_percent`, default `55`
- `steering.pending_invalidation_required_signals`, default `2`
- `steering.pending_price_chase_limit_percent`, default `1.0`
- `steering.cancel_invalidated_pending_orders_enabled`, default `true`

Default action: `cancel_pending_order`.

### Rule P3: keep uncertain pending order

Do not cancel solely because:

- news is missing
- analysis refresh failed
- market data is stale but broker reconciliation is otherwise healthy
- only one weak contradiction exists

Default action: `keep_pending_order` with reason `insufficient_invalidation_evidence`.

## Filled-position steering rules

Filled means the broker shows an app-owned open position or a filled order lifecycle tied to a broker position.

### Rule F1: never increase downside risk

The proposed stop-loss must never be worse than the current broker stop-loss or original plan stop-loss.

For a long position, proposed SL must be:

`>= max(current_stop_loss, original_stop_loss)`

For a short position, proposed SL must be:

`<= min(current_stop_loss, original_stop_loss)`

If this cannot be verified, do not amend broker exits.

Default action: `manual_review_required` if the app cannot prove the amendment is non-risk-increasing.

### Rule F2: close immediately on severe thesis invalidation

If a filled position's thesis is clearly broken, v1 may close the broker position immediately rather than only tightening exits.

A severe invalidation requires at least `steering.position_close_required_signals` of these signals:

- current calibrated confidence drops below `steering.position_close_confidence_percent`
- current actionability says `no_action`
- current analysis direction strongly contradicts the held position direction
- new severe ticker-specific negative event directly contradicts the original rationale
- price breaks the original stop-loss or a hard technical invalidation level while the broker position remains open
- broker/account reconciliation is healthy enough to prove the app-owned position and quantity, but the original linked exit orders are missing or stale

Default action: `close_position_now`.

Safety constraints:

- never close if broker ownership, quantity, or side is uncertain
- never close if the position is already closing or has an active market/exit order that would duplicate the close
- persist the close decision before submitting the broker mutation
- when the broker accepts a close request, immediately mark the local position lifecycle as `closing` with the raw close response and close order id if available; final win/loss/P&L still comes from broker fill/reconciliation evidence
- accepted close responses are 2xx broker responses whose status is absent or one of `accepted`, `submitted`, `queued`, `pending_new`, `new`, `partially_filled`, `filled`, `closed`, or `done_for_day`; rejected/failed/canceled/expired responses must not move the local lifecycle to `closing`
- in dry-run, record the proposed close without broker mutation

Tunable knobs:

- `steering.close_on_severe_invalidation_enabled`, default `true`
- `steering.position_close_confidence_percent`, default `40`
- `steering.position_close_required_signals`, default `3`

### Rule F3: move stop to small profit when price has moved enough

When a position has enough unrealized gain, protect at least a small profit.

For a long position, move SL to at least:

`entry_price * (1 + steering.min_profit_lock_percent / 100)`

when current price is at least:

`entry_price * (1 + steering.breakeven_trigger_percent / 100)`

For a short position, invert the formula.

Tunable knobs:

- `steering.breakeven_trigger_percent`, default `0.75`
- `steering.min_profit_lock_percent`, default `0.10`
- `steering.move_to_profit_enabled`, default `true`

Default action: `move_stop_to_breakeven_or_profit`.

### Rule F4: tighten stop when thesis deteriorates

If current evidence is materially worse than the original plan but not bad enough for immediate close, tighten the stop.

Deterioration signals:

- current calibrated confidence drops below `steering.position_min_hold_confidence_percent`
- current actionability says `no_action`
- new severe negative event contradicts original rationale
- price breaks a key support/momentum condition used by the plan
- volatility expands enough that original stop/target geometry is stale

If at least `steering.position_deterioration_required_signals` are true, propose a tighter SL.

For a long position, the proposed SL is the highest safe value among:

- current SL
- original SL
- entry small-profit lock if Rule F3 is active
- `current_price * (1 - steering.deterioration_stop_cushion_percent / 100)`

For a short position, invert the direction and choose the lowest safe value.

Tunable knobs:

- `steering.position_min_hold_confidence_percent`, default `50`
- `steering.position_deterioration_required_signals`, default `2`
- `steering.deterioration_stop_cushion_percent`, default `0.35`
- `steering.tighten_on_deterioration_enabled`, default `true`

Default action: `tighten_stop_loss`.

### Rule F5: lower take-profit when evidence weakens but price is favorable

When the position is profitable but the thesis weakens, prefer a smaller, more reachable target over waiting for the original TP.

For a long position, lower TP only if all are true:

- current price is above entry price
- proposed TP remains above current price by at least `steering.min_tp_distance_percent`
- proposed TP is below current TP
- proposed TP still locks a positive expected result if filled
- the same evidence deterioration conditions from Rule F4 are met

Conservative proposed TP for a long position:

`current_price * (1 + steering.weakened_thesis_tp_cushion_percent / 100)`

For a short position, invert the formula.

Tunable knobs:

- `steering.lower_tp_on_weakness_enabled`, default `true`
- `steering.weakened_thesis_tp_cushion_percent`, default `0.50`
- `steering.min_tp_distance_percent`, default `0.10`

Default action: `lower_take_profit` if broker supports the amendment safely; otherwise `manual_review_required`.

TP lowering is intended to become automated after dry-run review, not manual-review-only, because it reduces greed when the position is already favorable.

### Rule F6: keep exits when evidence is stable

If the plan remains valid and price has not crossed the profit-lock trigger, keep existing exits.

Default action: `keep_position_exits`.

### Rule F7: broker uncertainty blocks amendments

If broker reconciliation reports material drift, missing linked orders, ambiguous quantity, or unknown order ids, the steering engine must not mutate live broker exits.

Default action: `manual_review_required`.

## Decision priority

Evaluate in this order:

1. broker/reconciliation safety check
2. pending expiration cancellation
3. pending invalidation cancellation
4. filled-position non-risk-increase guard
5. filled-position severe-invalidation immediate close
6. filled-position profit-lock stop move
7. filled-position deterioration stop tightening
8. filled-position weakened-thesis TP lowering
9. keep/no-op decision

If multiple filled-position amendments are valid, v1 may submit both SL and TP changes in one broker-safe amendment when supported. If not supported, submit the stop-loss tightening first and defer take-profit changes.

## Settings namespace

All knobs live under a `steering.*` namespace so future rules can be added without overloading plan-generation or risk-management settings.

Initial defaults:

- `steering.enabled`: `false`
- `steering.dry_run`: `true`
- `steering.cancel_expired_pending_orders_enabled`: `true`
- `steering.cancel_invalidated_pending_orders_enabled`: `true`
- `steering.move_to_profit_enabled`: `true`
- `steering.close_on_severe_invalidation_enabled`: `true`
- `steering.tighten_on_deterioration_enabled`: `true`
- `steering.lower_tp_on_weakness_enabled`: `true`
- `steering.pending_expiration_grace_minutes`: `5`
- `steering.pending_min_confidence_percent`: `55`
- `steering.pending_invalidation_required_signals`: `2`
- `steering.pending_price_chase_limit_percent`: `1.0`
- `steering.breakeven_trigger_percent`: `0.75`
- `steering.min_profit_lock_percent`: `0.10`
- `steering.position_close_confidence_percent`: `40`
- `steering.position_close_required_signals`: `3`
- `steering.position_min_hold_confidence_percent`: `50`
- `steering.position_deterioration_required_signals`: `2`
- `steering.deterioration_stop_cushion_percent`: `0.35`
- `steering.weakened_thesis_tp_cushion_percent`: `0.50`
- `steering.min_tp_distance_percent`: `0.10`
- `steering.min_reviewed_dry_run_decisions_before_enable`: `30`
- `steering.min_reviewed_dry_run_amendments_before_enable`: `10`
- `steering.min_reviewed_dry_run_close_now_before_enable`: `10`

`steering.enabled=false` means no autonomous steering job mutates broker state.

`steering.dry_run=true` means the job persists steering decisions but does not submit broker cancellation/amendment calls.

The first implementation must ship with dry-run as the default.

The `min_reviewed_dry_run_*` threshold keys count persisted dry-run decisions in the current implementation; the historical `reviewed` label reflects the setting name, not a separate manual-review workflow.

## Architecture

Use a small rule engine with a pure decision core:

- `BrokerSteeringStateBuilder`: loads broker/order/position/plan/current-analysis/current-price state
- `BrokerSteeringEngine`: pure deterministic rules, no database, no broker client
- `BrokerSteeringExecutor`: applies approved decisions to Alpaca only when enabled and not dry-run
- `BrokerSteeringDecisionRepository`: persists decision audits
- scheduled job: evaluates open app-owned broker orders/positions periodically

The pure engine is the stable seam for tests and future rules.

Each rule should be small and independently testable. New rules should add reason codes and knobs rather than changing existing rule semantics silently.

## Persistence

Add a steering decision audit table before enabling broker mutations.

Minimum fields:

- id
- created_at
- recommendation_plan_id
- broker_order_id nullable
- broker_position_id nullable
- ticker
- decision
- execute_allowed
- executed_at nullable
- per-decision execution_status: `dry_run`, `submitted`, `succeeded`, `failed`, `blocked`
- run-level execution_status: `dry_run`, `no_action`, `blocked`, `partial_success`, `succeeded`, `failed`. Run status is aggregated after decision execution; it must not say `submitted` when every live decision was blocked.
- reason_codes JSON
- proposed_stop_loss nullable
- proposed_take_profit nullable
- current_price nullable
- current_stop_loss nullable
- current_take_profit nullable
- risk_delta nullable
- diagnostics JSON
- error_message nullable

This ledger is required for tuning, debugging, and operator trust.

## Broker execution safety

Before any broker mutation:

- reload broker state
- verify the app-owned order/position ids still match
- verify quantity and side match the decision input
- verify proposed amendments still satisfy non-risk-increase rules
- verify market is open or broker accepts the requested action
- persist the attempted mutation and result

Broker amendment method means how the app safely changes an already-submitted bracket order at Alpaca. Some brokers allow direct replacement of child stop/target orders; others require canceling and recreating child orders or replacing the whole bracket. The implementation must discover and test the safest Alpaca-supported method before live amendments leave dry-run.

If broker API amendment semantics are uncertain, v1 should cancel/replace only after explicit tests and manual review. Otherwise the system should stay in dry-run.

## Operator UI

Add a steering section to the broker/operator workflow, not a separate research-only page.

The UI should show:

- steering enabled/dry-run state
- latest steering decisions
- pending-order cancellations recommended/executed
- stop/target amendments recommended/executed
- manual-review-required cases
- reason codes and compact human summaries
- before/after SL/TP values
- broker execution result

Manual controls:

- run steering check now
- approve an individual dry-run decision, if safe executor support exists
- disable steering globally

## Observability

Every steering run emits observability events:

- `steering_run_started`
- `steering_decision_created`
- `steering_broker_mutation_attempted`
- `steering_broker_mutation_succeeded`
- `steering_broker_mutation_failed`
- `steering_run_completed`

Events must include run correlation id, ticker, plan id, decision, and reason codes.

## Test plan

Tests must be added before broker mutations are enabled.

Unit tests for `BrokerSteeringEngine`:

- expired pending order cancels after grace period
- pending order with only missing news is kept
- pending order with two strong invalidation signals cancels
- long SL never moves downward
- short SL never moves upward
- profitable long moves SL to entry plus small profit
- profitable short moves SL to entry minus small profit
- severe long thesis invalidation proposes immediate close
- severe short thesis invalidation proposes immediate close
- deteriorating profitable long tightens SL
- deteriorating profitable short tightens SL
- deteriorating profitable long lowers TP only above current price
- deteriorating profitable short raises TP only below current price
- broker uncertainty produces manual review
- ambiguous direction produces manual review
- no-op stable position keeps exits

Repository/API tests:

- steering decisions persist full before/after diagnostics
- dry-run decisions do not call broker client
- enabled executor records success/failure statuses
- settings round-trip through the settings API

Integration tests:

- scheduled steering job processes only app-owned open/submitted broker records
- broker state is reloaded before mutation
- stale decision input is blocked before execution

## Implementation checklist

Use this checklist to track implementation progress. Keep it updated as tasks move from planned to done.

### Phase 1: dry-run steering core

- [x] Add steering domain models/config/state/decision objects.
- [x] Implement pure `BrokerSteeringEngine` with no database or broker side effects.
- [x] Add pending-order rules: expiration cancel, invalidation cancel, uncertain keep.
- [x] Add filled-position rules: non-risk-increase guard, severe close-now, profit-lock SL, deterioration SL tighten, weakened-thesis TP lowering, stable keep.
- [x] Add unit tests for long and short rule behavior, broker uncertainty, ambiguous direction, missing evidence, and TP/SL safety.

### Phase 2: persistence/audit ledger

- [x] Add `broker_steering_decisions` migration and ORM model.
- [x] Add `BrokerSteeringDecisionRepository`.
- [x] Persist every steering decision, including dry-run/no-op/manual-review decisions.
- [x] Add repository tests for before/after levels, reason codes, diagnostics, and execution status.

### Phase 3: settings

- [x] Add `steering.*` defaults to settings repository/domain service.
- [x] Expose steering settings through backend settings API.
- [x] Add settings tests for defaults and round-trip updates.

### Phase 4: state builder

- [x] Add `BrokerSteeringStateBuilder` for app-owned broker orders/positions.
- [x] Load linked plan/order/position state and latest available market price.
- [x] Add conservative handling for missing news/analysis/price.
- [x] Add tests that only app-owned open/submitted records are eligible.

### Phase 5: dry-run job/service

- [x] Add `BrokerSteeringService.run_once()`.
- [x] Add scheduled/manual job type for steering dry-run.
- [x] Persist run summary counts by decision/action.
- [x] Emit observability events for run start, decision creation, and run completion.
- [x] Add service/job tests.

### Phase 6: API/UI visibility

- [x] Add API endpoint to list recent steering decisions.
- [x] Add API endpoint to trigger a dry-run steering check.
- [x] Add broker/operator UI section for latest decisions, reason codes, proposed SL/TP, and dry-run/live state.
- [x] Add frontend typecheck coverage.

### Phase 7: broker execution after dry-run evidence

- [x] Validate Alpaca bracket amendment method safely: direct replace vs child-leg cancel/replace vs full bracket replacement.
- [x] Enable expired pending-order cancellation first.
- [x] Enable non-risk-increasing SL amendments after dry-run sample threshold.
- [x] Enable TP lowering after dry-run sample threshold and broker amendment validation.
- [x] Enable severe-invalidation close-now only after dedicated dry-run review confirms no false positives.
- [x] Keep all live broker mutations blocked when steering is disabled, dry-run is enabled, broker state is uncertain, or dry-run sample thresholds are unmet.

## Rollout sequence

The shipped implementation followed this sequence; all phases below are now complete.

### Phase 1: dry-run decisions only (completed)

- implement state builder, pure engine, decision repository, settings, scheduled/manual run
- no broker mutation
- UI shows recommendations and reason codes
- compare decisions against operator judgment
- require at least 30 dry-run decisions, including at least 10 amendment decisions and 10 close-now decisions if those actions will be enabled

### Phase 2: safe pending-order cancellation (completed)

- enable autonomous cancellation only for expired pending orders
- keep invalidation cancellation in dry-run until enough dry-run examples have accumulated

### Phase 3: safe filled-position steering (completed)

- enable autonomous non-risk-increasing SL amendments after dry-run review
- enable TP lowering after dry-run review and broker amendment-method validation
- enable severe-invalidation close-now only after dedicated dry-run review confirms no false positives

### Phase 4: broader amendments (completed)

- consider partial exits
- consider trend-following target extension only if evidence supports it

## Review decisions captured

1. V1 supports both long and short app-owned positions.
2. Severe thesis invalidation may trigger `close_position_now` for filled positions.
3. Broker amendment method must be validated during implementation: direct replace vs child-leg cancel/replace vs full bracket replacement depends on Alpaca behavior and safety tests.
4. TP lowering should be eligible for automation after dry-run review, not manual-review-only.
5. Autonomous amendments require a minimum dry-run sample before enablement: default 30 total decisions, including 10 amendment decisions and 10 close-now decisions for those action families.
