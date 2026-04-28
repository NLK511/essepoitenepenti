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
- Proposal-generation jobs stay linked to the seeded watchlists by name.
- Regional bars refresh jobs (`Bars-APAC`, `Bars-EU`, `Bars-US`) derive their ticker list from the current regional watchlists at runtime, so rerunning the seed script keeps bars coverage aligned with watchlist changes.

### `scripts/reconstruct_context.py`
Rebuilds historical macro and industry context snapshots from NewsAPI-backed historical news windows.

- **Use case:** Recover lost shared-context data for a specific date range, or re-run the latest completed business week when no dates are supplied.
- **Behavior:** Iterates business days, rebuilds the macro snapshot plus all taxonomy-driven industry snapshots, and uses `request_mode=replay` so replay-safe provider selection applies. The backfill is rate-limit aware: it backs off on NewsAPI 429s, sleeps briefly between snapshot attempts, and stops after repeated consecutive rate-limit errors.
- **Usage:**
  ```bash
  .venv/bin/python scripts/reconstruct_context.py \
    --start-date 2026-04-20 \
    --end-date 2026-04-24 \
    --newsapi-api-key "$NEWSAPI_API_KEY"
  ```
- **Notes:** If `--start-date` / `--end-date` are omitted, the script defaults to the latest completed business week. Use `--industry-key` to limit the scope when you do not want the full taxonomy-driven rebuild. `--inter-request-delay-seconds`, `--rate-limit-backoff-seconds`, and `--max-consecutive-rate-limit-errors` can be used to tune NewsAPI throttling behavior.

### `scripts/cleanup_context_missing_primary_sources.py`
Reports and optionally deletes macro and industry context snapshots that were created without primary news evidence.

- **Use case:** Clean up reconstructed context rows that fell back to secondary-only evidence or have zero primary-news items.
- **Behavior:** Scans context snapshots, flags rows with `primary_news_evidence` / `primary_industry_news_evidence` missing inputs or a zero `primary_news_item_count`, and can delete only those rows when run with `--apply --yes`.
- **Usage:**
  ```bash
  .venv/bin/python scripts/cleanup_context_missing_primary_sources.py \
    --start-date 2026-04-20 \
    --end-date 2026-04-24
  ```
- **Notes:** Dry-run by default. Use `--macro-only` or `--industry-only` to narrow scope. Add `--json` or `--output <path>` for machine-readable reports.

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
