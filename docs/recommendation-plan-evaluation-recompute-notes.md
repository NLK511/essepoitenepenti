# Recommendation Plan Evaluation Recompute Notes

**Status:** active implementation notes

This document records the evaluation/recompute work that was done around the EOG plans (`315`, `635`) and the surrounding architecture choices.

## Why this work happened

The evaluation pipeline had two competing goals:

1. **Point-in-time correctness**: only use market data that was actually available when the plan would have been evaluated.
2. **Recomputability**: allow the evaluation algorithm to change and still recompute past plans when the logic improves.

The bug surfaced because the evaluator was mixing daily bars, intraday bars, and historical persistence rules in a way that caused plans to stay `pending` / `no_entry` or be misclassified.

## Core architectural choice

Recommendation-plan evaluation is a **derived, recomputable artifact** rather than a one-time immutable judgment.

That means:
- the source of truth is the stored recommendation plan plus market history
- the stored outcome can be refreshed when the evaluator is corrected
- recomputation is a normal operation, not an exceptional one

Operationally, scheduled jobs should only process open plans, while manual single-plan evaluation may revisit a previously closed plan when specifically requested.

This document records the implementation history and known pitfalls. The canonical resolution semantics themselves are defined in `recommendation-plan-resolution-spec.md`.

## Current implementation snapshot

This section is a reconciliation aid: it describes what the codebase has already implemented versus what still needs to be aligned to the canonical spec.

### Already implemented
- outcome rows are derived and recomputable
- the evaluator stores intraday resolution fields such as entry/stop/take hits
- recomputation can overwrite stored outcomes
- daily history fallback handling exists for incomplete persisted windows
- manual specific-plan evaluation paths exist conceptually through targeted triggers

### Still to reconcile
- remove or fence off legacy session-based daily-vs-intraday selection as the final decision path
- enforce batch open-plan filtering in the scheduler/worker path
- ensure daily bars remain prefilter-only in practice, not just in documentation

## What changed in the evaluator

### 1. Point-in-time bar selection

The evaluator now uses `available_at` where possible instead of relying on bar timestamps alone, and it also respects the `as_of` cutoff when loading history for recomputes.

That matters because:
- a bar’s timestamp is not always the same as when it became available
- daily data and intraday data have different visibility rules
- persisted historical bars need to be filtered by availability, not just by date
- recomputes should not accidentally peek past the requested `as_of` timestamp

### 2. Daily vs intraday selection

The earlier evaluator tried to switch between daily and intraday bars based on session timing. That is the exact class of behavior that caused the `315` / `635` mismatch.

Current canonical guidance is now defined in `recommendation-plan-resolution-spec.md`:
- use daily bars only as a cheap prefilter
- use intraday bars as the source of truth for final win/loss resolution
- do not use a daily-bar shortcut as the final outcome path for same-day or post-close plans

This section is kept as historical context only. New evaluator work should follow the resolution spec, not the old session-based compromise.

### 3. yfinance normalization

Live `yfinance` data can arrive as a `MultiIndex`, even for single-ticker downloads.

We normalized that output before evaluation so the evaluator can always access:
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`
- `available_at`

Without this, the evaluator could silently read the wrong columns or fail to classify entry/exit.

### 4. Persisted-history completeness fallback

A later regression showed that persisted daily history can be present but still incomplete for the requested recompute window.

For example, plan `635` had only `2026-03-30` persisted daily bars available even though the recompute `as_of` was `2026-03-31`, so trusting the cache produced a false `no post-plan bars` result.

The evaluator now checks whether the persisted frame actually covers the requested window. If it does not, it falls back to `yfinance` instead of using a partial cache.

The fallback is logged with:
- ticker
- plan ids
- intraday vs daily mode
- row count
- first and last persisted timestamps
- the requested cutoff

That keeps the recompute path point-in-time correct without pretending an incomplete cache is authoritative.

### 5. Gap-through entry handling

Entry detection was tightened so a bar that opens through the entry zone can count as a valid fill.

That fixed a real class of false `no_entry` outcomes.

### 6. Recompute overwrite semantics

We explicitly allow recomputation to overwrite the stored outcome.

This is the key operational compromise:
- the latest evaluator result should win
- we are not yet keeping a full versioned outcome history in the main table

So if the algorithm changes, the same plan can be reevaluated and the stored outcome updated.

## Historical implementation note

The earlier implementation used a session heuristic to decide whether to read daily or intraday bars first.

That approach is now superseded by the canonical resolution spec. It remains here only so the earlier EOG debugging context is understandable.

## Pitfalls we encountered

### 1. Legacy same-day daily-bar shortcut

A major semantic mismatch was the attempt to treat same-day daily bars as a final resolution source for intraday-style plans.

That was the root of the `315` vs `635` confusion:
- using same-day daily bars too early can manufacture a loss from incomplete timing information
- excluding too much intraday information can misclassify a valid loss as `no_entry`

The fix is to treat daily bars as a prefilter only and resolve the actual outcome from intraday timestamps.

### 2. Single-ticker `yfinance` can still return `MultiIndex`

Even when downloading one ticker, the response may still have a `MultiIndex` column layout.

That caused incorrect OHLC access until we flattened the frame consistently.

### 3. Historical persistence schema drift

Some environments did not have an `available_at` column in `historical_market_bars`.

We had to infer availability for persisted bars to keep point-in-time evaluation working across schema variants.

### 4. Transaction state / rollback issues

The evaluation job and outcome repository both had to be hardened against aborted transactions and `IntegrityError` states.

Without rollback discipline, a failure in one part of the pipeline could poison the rest of the evaluation.

### 5. Outcome overwrite behavior can hide the earlier truth

Because recompute overwrites the stored outcome, the table always shows the latest algorithmic judgment.

That is intentional, but it also means the system does not yet preserve a full “what did we think before?” history in the main outcome row.

## Blind spots we still have

### 1. No full exchange calendar

The current session detection is still heuristic.

Future blind spots include:
- holidays
- half-days
- premarket and after-hours
- non-US exchanges with different rules
- region/ticker misclassification in taxonomy

### 2. Recompute history is not versioned in the primary outcome row

We can recompute and overwrite, but we do not yet keep a first-class version history of outcome changes.

That means postmortems still depend on external logs, git history, or ad hoc snapshots.

### 3. Intraday availability is inferred, not guaranteed

For persisted bars and fallback data, `available_at` is often inferred from interval length or end-of-day assumptions.

This is useful, but it is still an approximation.

### 4. The latest algorithm can still be wrong

The evaluator is more robust now, but it is not mathematically proven.

Any future change to:
- entry rules
- stop/take ordering
- same-bar ambiguity
- session gating
- data fallback precedence

can reintroduce misclassification if not covered by regression tests.

### 5. `run_id` and integration behavior matter

In real Postgres recomputes, the output is linked to a real `run_id`.

That means tests must use valid runs, not invented IDs, or they will hit foreign-key constraints.

## What we validated

We added and ran coverage for:
- long/short entry and exit behavior
- no-entry cases
- gap-through fills
- stop/take ordering
- same-bar ambiguity
- MultiIndex `yfinance` normalization
- persisted-bar availability handling
- recompute overwrite behavior
- a real Postgres integration test for EOG plans `315` and `635`
- an explicit real Postgres regression test showing plan `315` resolves to a stop loss when the recompute happens after market close
- a regression test showing incomplete persisted daily history falls back to `yfinance` instead of being trusted as a complete recompute window

## Practical takeaway

If you are changing the evaluator in the future, remember:

1. **Never assume bar timestamps equal bar availability.**
2. **Use daily bars only as a prefilter; intraday bars are the resolution source of truth.**
3. **Recompute is allowed to overwrite the stored outcome when the evaluator or data window was wrong.**
4. **Do not reintroduce a session-based daily-final-resolution path.**
5. **Treat incomplete persisted history as incomplete; fall back instead of guessing.**
6. **Keep a regression test for the real EOG plans, not just synthetic fixtures.**

## Related files

- `src/trade_proposer_app/services/recommendation_plan_evaluations.py`
- `src/trade_proposer_app/repositories/historical_market_data.py`
- `src/trade_proposer_app/repositories/recommendation_outcomes.py`
- `tests/test_recommendation_plan_evaluations.py`
- `tests/test_repositories.py`
- `tests/test_postgres_integration.py`
