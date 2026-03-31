# Recommendation Plan Evaluation Recompute Notes

**Status:** active implementation notes

This document records the evaluation/recompute work that was done around the EOG plans (`315`, `635`) and the surrounding architecture choices.

## Why this work happened

The evaluation pipeline had two competing goals:

1. **Point-in-time correctness**: only use market data that was actually available when the plan would have been evaluated.
2. **Recomputability**: allow the evaluation algorithm to change and still recompute past plans when the logic improves.

The bug surfaced because the evaluator was mixing daily bars, intraday bars, and historical persistence rules in a way that caused plans to stay `pending` / `no_entry` or be misclassified.

## Core architectural choice

We chose to make recommendation-plan evaluation a **derived, recomputable artifact** rather than a one-time immutable judgment.

That means:
- the source of truth is the stored recommendation plan plus market history
- the stored outcome is meant to be **replaceable** when the algorithm changes
- recomputation is a normal operation, not an exceptional one

This is important because the algorithm is still evolving. If the evaluator improves, we want to be able to run it again and refresh the stored outcome.

## What changed in the evaluator

### 1. Point-in-time bar selection

The evaluator now uses `available_at` where possible instead of relying on bar timestamps alone, and it also respects the `as_of` cutoff when loading history for recomputes.

That matters because:
- a bar’s timestamp is not always the same as when it became available
- daily data and intraday data have different visibility rules
- persisted historical bars need to be filtered by availability, not just by date
- recomputes should not accidentally peek past the requested `as_of` timestamp

### 2. Daily vs intraday selection

We settled on a compromise:
- **current-session plans** may use intraday bars while the evaluation run is still inside market hours
- **prior-session plans** use daily bars
- once the evaluation run is **after the market close**, same-day plans should be resolved from daily bars so a real stop-loss can be captured instead of leaving the plan pending

This was done because using intraday for all plans was too aggressive and caused earlier plans like `315` to lose their daily-bar loss classification.

The current-session check is a heuristic, not a full exchange-calendar engine.

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

### 4. Gap-through entry handling

Entry detection was tightened so a bar that opens through the entry zone can count as a valid fill.

That fixed a real class of false `no_entry` outcomes.

### 5. Recompute overwrite semantics

We explicitly allow recomputation to overwrite the stored outcome.

This is the key operational compromise:
- the latest evaluator result should win
- we are not yet keeping a full versioned outcome history in the main table

So if the algorithm changes, the same plan can be reevaluated and the stored outcome updated.

## The compromise we made

We did **not** implement a full exchange-calendar / session engine.

Instead, we used a pragmatic approximation:
- infer region/timezone from the ticker taxonomy
- infer whether the plan is “current session” from local market date and trading hours
- prefer intraday bars only when that heuristic says the plan is in-session

This is good enough to fix the current bug class, but it is not perfect.

### Why this compromise was acceptable

A proper exchange-calendar implementation would be more accurate, but it would also require:
- exchange-specific holiday calendars
- half-day handling
- premarket/after-hours policy
- cross-listed instrument rules
- more maintenance overhead

The current heuristic is a smaller change that preserves most point-in-time behavior while still enabling recomputation.

## Pitfalls we encountered

### 1. Same-day daily bar semantics

A major semantic mismatch was whether same-day daily bars should count for intraday `computed_at` plans.

That question was the root of the `315` vs `635` confusion:
- if you include same-day daily bars too early, you can manufacture a `loss`
- if you exclude them too aggressively, you can misclassify a valid loss as `no_entry`

We eventually kept the rule conservative and made current-session logic explicit.

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

## Practical takeaway

If you are changing the evaluator in the future, remember:

1. **Never assume bar timestamps equal bar availability.**
2. **Do not rely on daily bars when the plan is effectively intraday.**
3. **Recompute is allowed to overwrite the stored outcome.**
4. **The current session heuristic is a compromise, not a perfect calendar.**
5. **Keep a regression test for the real EOG plans, not just synthetic fixtures.**

## Related files

- `src/trade_proposer_app/services/recommendation_plan_evaluations.py`
- `src/trade_proposer_app/repositories/historical_market_data.py`
- `src/trade_proposer_app/repositories/recommendation_outcomes.py`
- `tests/test_recommendation_plan_evaluations.py`
- `tests/test_repositories.py`
- `tests/test_postgres_integration.py`
