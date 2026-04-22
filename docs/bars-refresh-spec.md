# Bars Refresh Spec

**Status:** canonical current behavior for `bars_data_refresh` jobs

This document answers one question:
> how should the bars refresh job fetch and persist intraday bars today?

It is the source of truth for bars-refresh behavior.

## Goal

The bars refresh job exists to keep local `1m` market bars reasonably fresh without making the whole run brittle to partial provider noise.

The job should:
- refresh as many tickers as possible in one run
- avoid re-fetching tickers that already succeeded in the same run
- tolerate transient provider failures
- make unresolved failures visible to the operator
- persist enough diagnostics to judge whether retry logic is useful

## Scope

This spec covers:
- `BarsRefreshService.refresh_bars`
- run artifacts and warnings produced by `bars_data_refresh` runs

This spec does not cover:
- cheap-scan remote retry behavior
- deep-analysis remote retry behavior
- replay-time market-data fetching

## Current implemented behavior

### Fetch target
- The job refreshes `1m` bars from Yahoo/yfinance.
- For each ticker, it starts from the later of:
  - `now - lookback_days`
  - the latest persisted `1m` `bar_time` for that ticker plus one minute

### Up-to-date skip
- If the computed start time is less than 10 minutes behind `now`, the ticker is treated as already up to date.
- Already-up-to-date tickers are not fetched remotely.
- Their `ticker_stats` entry is `0`.

### Retry model
- The job makes a bounded number of passes over unresolved tickers.
- Default maximum attempts per ticker: `3`.
- Attempt 1 runs over the full ticker list.
- Later attempts run only over tickers that are still unresolved.
- A ticker is considered unresolved when a fetch attempt:
  - raises an exception, or
  - returns no data from Yahoo/yfinance
- Small backoff is allowed between retry passes.

### Completion model
A ticker is considered complete for the run when one of these happens:
- new bars were ingested successfully
- the ticker was already up to date
- Yahoo returned bars, but there were no bars newer than the computed start time
- Yahoo returned rows, but none could be converted into valid bar models

Completed tickers must not be retried in later passes of the same run.

### Warning model
- A single ticker failure must not abort the whole bars-refresh run.
- Warnings are emitted only after the ticker has exhausted its bounded retries.
- Final unresolved outcomes are recorded as warnings in the run result.
- `ticker_stats[ticker]` values:
  - positive integer = number of ingested bars
  - `0` = no ingestion, but not a terminal exception failure
  - `-1` = terminal exception failure after retries

### Run artifact diagnostics
The result artifact returned by `refresh_bars` must include:
- `total_ingested`
- `ticker_stats`
- `warnings`
- `refreshed_at`
- `retry_diagnostics`

`retry_diagnostics[ticker]` must include:
- `attempt_count`
- `attempts`

Each attempt entry must include:
- `attempt`
- `status`
- `ingested`
- `message`

## Tests required by this spec

The automated tests must cover at least:
- incremental refresh still ingests only bars newer than the latest persisted bar
- a ticker that first returns empty and then succeeds is retried and eventually ingested
- a ticker that keeps raising exceptions is retried up to the cap and ends as a warning
- completed tickers are not retried after they succeed

## Current limitations

- Empty results are retried even though some empties may be structurally non-recoverable.
- Retry classification is still coarse; it does not yet distinguish likely-transient empties from likely-permanent empties.
- Retry diagnostics are persisted in run artifacts, but operator-facing UI rendering is still minimal.
