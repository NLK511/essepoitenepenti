# Operational Scripts Reference

**Status:** canonical reference for developer and operator tools

This document lists the standalone scripts available in the `scripts/` directory for maintenance, hydration, and regression testing.

## Data Hydration

### `scripts/hydrate_daily_bars.py`
Hydrates the local database with historical Daily OHLCV bars from Yahoo! Finance.

- **Use case:** Fixes "insufficient history" issues in replays by backfilling the 30-90 days of history required for SMA/momentum indicators.
- **Behavior:** Pulls point-in-time consistent bars (using `as_of`) and persists them to `historical_market_bars`.
- **Usage:**
  ```bash
  .venv/bin/python scripts/hydrate_daily_bars.py
  ```
  *(Note: Hardcoded for core watchlists 7, 11, 13 by default; edit the script to change scope.)*

## Regression Testing and Debugging

### `scripts/compare_replay_confidence_regression.py`
Performs a side-by-side comparison of a replay run between the current "fixed" code and a simulated "buggy" version.

- **Use case:** Verifies that point-in-time context (Macro/Industry snapshots) is being correctly applied to historical runs.
- **Behavior:** Runs the orchestration twice (Fixed vs Buggy) on the same tickers/date and prints a JSON delta of confidence scores and actions.
- **Usage:**
  ```bash
  .venv/bin/python scripts/compare_replay_confidence_regression.py \
    --watchlist-id <id> \
    --as-of <ISO-TIMESTAMP> \
    [--limit-tickers <count>] \
    [--disable-social]
  ```

## Setup and Launch

### `scripts/start-prod.sh`
The canonical "production-style" launch script for the complete application stack.

- **Capabilities:**
  - Loads `.env`
  - Builds frontend assets
  - Applies database migrations
  - Runs preflight checks
  - Starts API, Worker, and Scheduler
  - **New:** Provides centralized logging in `.prod-run/` (`api.log`, `scheduler.log`, `worker.log`).
  - **New:** Detailed exit reporting if any background process crashes.

### `scripts/stop-prod.sh`
Stops all processes started by `start-prod.sh` using stored PID files.

### `scripts/setup.sh`
Initializes the local environment, virtual environment, and dependency stack.

## Maintenance

### `scripts/deploy_watchlists.py`
Seeds or updates the canonical default watchlist pack in the database.

### `scripts/reconstruct_context.py`
Re-runs the context extraction engine on past news/social data to build historical context snapshots for backtesting.
