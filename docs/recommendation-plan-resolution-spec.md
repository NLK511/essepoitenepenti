# Recommendation plan resolution spec

**Status:** canonical reference

This document defines the intended resolution semantics for `RecommendationPlan` outcomes.

It is the static reference to use when evaluating, recomputing, tuning, or refactoring plan outcome logic.

## Canonical behavior vs implementation status

This document defines the **expected behavior** for plan resolution.

It is intentionally stricter than the current evaluator in a few places so that future work can reconcile the codebase back to a single rule set.

Use the notes below as the canonical target and `recommendation-plan-evaluation-recompute-notes.md` as the current implementation history.

### Expected behavior

A recommendation plan is an **intraday execution problem**.

For resolution purposes, every plan should be treated as an order intended to be entered:

- immediately, or
- within 5 minutes of the next market open

This applies whether the plan was generated:

- during market hours, or
- at market close

### Current implementation status

- **Partially aligned:** the evaluator already stores resolution outcomes and supports recomputation.
- **Not yet fully aligned:** the live evaluator still contains legacy session-based selection behavior; see the recompute notes for details.
- **Not yet fully aligned:** batch open-plan filtering should be the default policy, but may still need to be enforced in the execution path.

## What counts as resolution

A plan is resolved when the market data proves, in timestamp order, that one of the following happened first after the assumed entry point:

- the entry condition was touched and then the take profit was hit first, or
- the entry condition was touched and then the stop loss was hit first

Once that first crossing is established, the outcome is final.

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

- `recommendation-plan-evaluation-recompute-notes.md`
- `recommendation-methodology.md`
- `signal-gating-tuning-plan.md`
