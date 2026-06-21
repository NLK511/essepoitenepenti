# Recommendation plan resolution spec

**Status:** current + target behavior

This document defines the intended resolution semantics for `RecommendationPlan` outcomes.

It is the static reference to use when evaluating, recomputing, tuning, or refactoring plan outcome logic.

## Canonical behavior vs implementation status

This document remains a `current + target behavior` spec by design. The conformance matrix below is the boundary between shipped behavior and stricter target semantics; do not read target-only sections as already implemented unless the matrix says they are aligned.

This document defines the **expected behavior** for plan resolution.

It is intentionally stricter than the current evaluator in a few places so that future work can reconcile the codebase back to a single rule set.

Use the notes below as the canonical target and `../archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md` as the current implementation history.

### Expected behavior

A recommendation plan is an **intraday execution problem**.

For resolution purposes, every plan should be treated as an order intended to be entered:

- immediately, or
- within 5 minutes of the next market open

This applies whether the plan was generated:

- during market hours, or
- at market close

### Current implementation status

- **Aligned for current core crossing logic:** a dedicated `PlanResolutionEngine` owns entry touch, stop/take ordering, conservative same-bar ties, no-entry diagnostics, phantom outcomes, and realism buffers without database/session dependencies.
- **Partially aligned for orchestration:** `RecommendationPlanEvaluationService` still owns history loading, daily/intraday source selection, persistence, and expiration finalization.
- **Aligned for intraday precedence:** when intraday bars are available, they are used as the resolution source even if daily bars disagree.
- **Still target behavior:** the immediate-or-next-open entry window should become a first-class engine policy if execution semantics tighten further.

### Implementation conformance matrix

| Rule | Current status | Code owner | Test owner | Gap |
|---|---|---|---|---|
| Entry touch detection | Implemented | `PlanResolutionEngine.find_entry_index()` | `tests/test_plan_resolution_engine.py`, `tests/test_recommendation_plan_evaluations.py` | None known for current bar model. |
| Stop/take first crossing | Implemented | `PlanResolutionEngine.resolve_exit()` | `tests/test_plan_resolution_engine.py`, `tests/test_recommendation_plan_evaluations.py` | Same-bar tie remains conservative loss by policy. |
| Near-entry diagnostics | Implemented | `PlanResolutionEngine.entry_miss_distance_percent()` | `tests/test_plan_resolution_engine.py`, evaluator tests | None known. |
| Phantom outcomes | Implemented | `PlanResolutionEngine.evaluate_plan()` plus evaluator intended-action routing | `tests/test_plan_resolution_engine.py`, evaluator tests | None known for current intended-action payload. |
| Expiration | Implemented in orchestration | `RecommendationPlanEvaluationService._finalize_outcome()` | evaluator tests | Could move into the engine later if expiration policy needs pure-unit coverage. |
| Batch unresolved filtering | Implemented for default evaluation path | `RecommendationPlanEvaluationService._list_plans()` | evaluator/repository tests | Manual explicit ids can still reevaluate resolved plans by design. |
| Daily bars as prefilter only | Mostly aligned | `RecommendationPlanEvaluationService._resolve_trade_like_outcome()` | evaluator tests | Daily no-entry/open states can still be used when intraday is absent; terminal daily outcomes require intraday. |
| Intraday truth for terminal order | Implemented when intraday is available | history loading + resolution orchestration | evaluator tests | Depends on available intraday bars and provider/persistence coverage. |

## Live broker execution precedence

When a plan has a live Alpaca broker-order record, operator-facing views should treat the broker-backed execution state as the primary evaluation source for that plan. That means the broker signal should supersede the simulated plan outcome in the main UI/status path when it exists.

A broker order that ends in a terminal failure state (`failed`, `rejected`, `canceled`, or `expired`) is not a pending broker evaluation. It should be treated as a missing broker evaluation, with simulated resolution used only as a fallback if available.

Current broker reconciliation can prove the live order lifecycle up through entry timing and pending status. Simulated market-data resolution remains the fallback for plans without broker execution data, and it remains useful for deeper analytics until live exit tracking is added.

## What counts as resolution

A plan is resolved when either:

- the market data proves, in timestamp order, that the entry condition was touched and then the take profit was hit first, or
- the market data proves, in timestamp order, that the entry condition was touched and then the stop loss was hit first, or
- the plan remains unresolved until its intended horizon has elapsed, in which case it must be resolved as `expired`

Once that first crossing or terminal expiration is established, the outcome is final.

## Expiration rule for overdue pending plans

A recommendation plan must not remain `pending`, `open`, or `no_entry` forever.

## Trade Review filter consistency

The Trade Review page may stage loading so the plan queue renders before heavier analytics. However, every visible analytics widget that claims to describe the reviewed cohort must use the same active filters as the plan list, including ticker, setup family, run id, plan id, resolved state, outcome, shortlist/entry filters, and the selected review window. If a widget intentionally uses a broader baseline, label it as a broader baseline.

If the plan is still unresolved after the full generated horizon has passed, the evaluator must convert it to:

- `outcome = "expired"`
- `status = "resolved"`

This rule exists to prevent stale plans from lingering in the open set after their intended evaluation window is no longer valid.

## Near-entry miss diagnostics

Some expired or `no_entry` plans are not pure thesis failures.

A plan can miss entry by a very small amount and then still move in the forecasted direction. The evaluator should keep the execution truth (`no_entry` while open, `expired` after the horizon), but it should also record extra diagnostics so the operator can distinguish:

- bad thesis
- bad fill framing
- almost-entered plans that likely needed a less strict entry zone

### Expected behavior

For plans that never touch entry, the evaluator should also record:

- the closest miss distance to the entry zone, expressed as a percent of the entry reference
- whether that miss qualifies as a `near_entry_miss`
- whether price still moved in the forecasted direction without entry (`direction_worked_without_entry`)

These diagnostics are:

- **not** alternative outcomes
- **not** wins or losses
- **not** part of headline win-rate math
- intended for review, diagnostics, and later entry-tuning work

### Fixed threshold policy

To avoid hindsight fitting, near-miss detection should use a fixed rule.

Current rule:
- `near_entry_miss = true` when the closest miss distance is at most `0.25%` of the entry reference

That threshold may be changed later, but only by explicit spec change and corresponding regression tests.

### Current implementation status

- **implemented now:** `no_entry` and later `expired` outcomes retain `entry_miss_distance_percent`, `near_entry_miss`, and `direction_worked_without_entry`
- **implemented now:** these diagnostics preserve execution truth instead of relabeling near-miss plans as wins
- **not implemented yet:** alternate-fill simulation, ATR-scaled miss thresholds, and automatic entry retuning based on these diagnostics

## Phantom trades (Recall optimization)

To enable recall optimization, the system tracks "phantom trades" for plans where the system decided **not** to trade (`action = "no_action"` or `watchlist`).

### Expected behavior

If a `no_action` plan carries an `intended_action` (long or short) and valid entry/stop/target levels, the evaluator must load market history for that plan and simulate it through the market exactly as if it were a real trade.

- If it hits the target, it resolves as `phantom_win`.
- If it hits the stop-loss, it resolves as `phantom_loss`.
- If it misses the entry, it resolves as `phantom_no_entry`.

### Interpretation of phantom outcomes

- `phantom_win` means the system missed a profitable opportunity.
- `phantom_loss` means the system correctly avoided a bad setup.
- All phantom outcomes receive `status = "resolved"` when terminal, and remain `"open"` while pending.

These phantom outcomes are ignored by default operator win-rate metrics, but are loaded by the tuning engines to learn if the system should have lowered its confidence threshold to capture the missed wins.

### Interpretation of `expired`

`expired` is a **terminal resolved lifecycle state**.

It means:
- the plan's evaluation window ended
- no qualifying terminal win/loss resolution was proven before the cutoff
- the plan should leave the open queue

It does **not** mean:
- automatic win
- automatic loss
- that the plan should be silently discarded from audit history

### Tuning and review treatment

For downstream review and tuning:
- `expired` should be treated as **resolved** for lifecycle/open-vs-closed purposes
- `expired` should remain visible in audit and operator review surfaces
- `expired` should **not** be counted as a `win` or `loss` unless a future methodology change explicitly says otherwise

## Immutable outcome rule

If a plan has already been resolved as a win or loss, that result is canonical unless a manual reevaluation explicitly proves the evaluator or input window was wrong.

In that case, the stored record may be refreshed, but the resolution concept itself does not change.

## Role of daily bars

### Expected behavior

Daily bars may be used only as a **prefilter**.

Their purpose is to answer:

- can this day possibly contain an entry touch?
- can this day possibly contain a stop-loss touch?
- can this day possibly contain a take-profit touch?

Daily bars must **not** be the final source of truth for outcome resolution when intraday ordering matters.

If a day remains plausible after the daily filter, intraday bars must be used to resolve the actual first-crossing order.

### Current implementation status

- daily bars are still used in the evaluator pipeline today
- the legacy path has historically mixed daily and intraday selection heuristics
- the canonical target is to keep daily bars as a prefilter only

## Role of intraday bars

### Expected behavior

Intraday bars are the source of truth for outcome resolution.

Use intraday data to determine:

- exact entry-touch timing
- exact stop-loss timing
- exact take-profit timing
- which threshold was crossed first
- whether both thresholds were touched on the same bar

If both stop and take are touched on the same bar and the order cannot be proven, resolve conservatively according to the evaluator’s tie-break rule.

### Current implementation status

- the evaluator already has intraday resolution logic and same-bar tie-break handling
- the remaining work is to make intraday truth the only final outcome path for plans that can be resolved by timestamp order

## Recommended evaluation flow

1. Load daily history as a cheap screen.
2. Reject days that cannot possibly touch the relevant thresholds.
3. For remaining candidate windows, load intraday bars.
4. Resolve the plan using timestamp order from intraday data.
5. Store the final win/loss result.

## Operational policy for scheduled and manual evaluation

### Expected behavior

Scheduled evaluation jobs should only process plans that are still **open**.

That means the batch path should:
- resolve unresolved plans
- skip already resolved plans
- avoid spending resources on closed outcomes that are already known

A plan that has already been resolved should only be reevaluated when a user explicitly triggers evaluation for that specific plan.

That manual path exists for:
- evaluator corrections
- data-window fixes
- regression validation on a specific plan

It should not be used as the default batch path.

### Current implementation status

- the manual single-plan path exists conceptually through specific evaluation triggers
- batch open-plan filtering is the intended default and should be enforced wherever the scheduler or worker enumerates plans
- legacy evaluation flows may still need reconciliation so that closed plans are excluded from routine runs

### Practical consequence
- **batch evaluation** = open plans only
- **manual single-plan evaluation** = may include previously closed plans
- **closed plans** should not be reevaluated by scheduled jobs
- overdue open plans should be closed automatically as `expired`

## What not to do

Do not:

- use daily bars as the final outcome source when intraday ordering matters
- reinterpret a previously resolved threshold crossing just because a later run used a different bar granularity
- treat same-day and next-day evaluation as different outcome semantics

## Reconciliation checklist

Use this when aligning code to the spec:

- daily bars are prefilter-only
- intraday bars decide final win/loss
- scheduled jobs skip closed plans
- manual single-plan evaluation may revisit closed plans
- legacy session-based shortcut logic should be removed or fenced off

## Why this matters

This spec preserves the meaning of resolution:

- the app is modeling trade execution, not daily swing summaries
- the exact hour, minute, and second of threshold crossing matter
- daily data is still useful for performance and pruning, but not for final truth

## Related docs

- `../archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md`
- `../recommendation-methodology.md`
- `../signal-gating-tuning-guide.md`
