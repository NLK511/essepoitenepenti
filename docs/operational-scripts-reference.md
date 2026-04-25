# Operational Scripts Reference

**Status:** canonical reference for developer and operator tools

This document lists the standalone scripts available in the `scripts/` directory for maintenance, hydration, and regression testing.

## Data Hydration

### `scripts/hydrate_daily_bars.py`
Hydrates the local database with historical Daily OHLCV bars from Yahoo! Finance.

- **Use case:** Fixes "insufficient history" issues in replays by backfilling the 30-90 days of history preferred by the cheap scan. Replays can run with as few as 10 bars, but the `cheap scan used limited lookback history` warning now specifically means fewer than 50 bars were available for the SMA50-style trend context.
- **Behavior:** Pulls point-in-time consistent bars (using `as_of`) and persists them to `historical_market_bars`.
- **Usage:**
  ```bash
  .venv/bin/python scripts/hydrate_daily_bars.py
  ```
  *(Note: The current script uses a fixed `as_of` date and hydrates tickers from watchlists with 100 tickers or fewer; edit the script to change scope.)*

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

### `scripts/report_legacy_non_shortlisted_plans.py`
- Read-only audit helper for identifying historical cheap-scan-only `RecommendationPlan` rows that were created for non-shortlisted tickers before the persistence-policy change.
- Useful before any manual archive/delete pass so we do not remove shortlisted or phantom-trade-eligible history by mistake.
- Example:

  ```bash
  .venv/bin/python scripts/report_legacy_non_shortlisted_plans.py --limit 100 --output legacy-non-shortlisted.json
  ```

### `scripts/cleanup_legacy_non_shortlisted_plans.py`
- One-off cleanup helper for the same legacy rows.
- Defaults to **dry-run**.
- In `--apply` mode it preserves decision samples, nulls their `recommendation_plan_id`, deletes linked outcome rows, then deletes the legacy plan rows.
- Requires both `--apply` and `--yes` before making changes.
- Example:

  ```bash
  .venv/bin/python scripts/cleanup_legacy_non_shortlisted_plans.py --apply --yes --output legacy-cleanup-backup.json
  ```
