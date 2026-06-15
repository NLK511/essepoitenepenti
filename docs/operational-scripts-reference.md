# Operational Scripts Reference

**Status:** reference

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

## Regression Testing and Release Validation

### `scripts/check_broker_migration_backfill.py`
Runs a broker-account migration/backfill smoke test against a fresh SQLite database.

- **Use case:** Verifies Alembic can upgrade to head and that broker-account tables, account-scoped columns, safety tables, and the default Alpaca paper account exist.
- **Usage:**
  ```bash
  .venv/bin/python scripts/check_broker_migration_backfill.py
  ```
- **Optional persistent database path:**
  ```bash
  .venv/bin/python scripts/check_broker_migration_backfill.py \
    --database-path /tmp/broker-migration-smoke.db
  ```

### `scripts/start_test_postgres.py`
Starts a local Docker Postgres container for migration/backfill validation and prints the required `POSTGRES_TEST_DATABASE_URL` export.

- **Use case:** Provides the environment needed by `scripts/check_postgres_validation.py` when a shared Postgres test database is not already available.
- **Defaults:** container `aurelio-postgres-test`, image `postgres:16-alpine`, port `55432`, database/user `aurelio_test`/`aurelio`.
- **Requirement:** the current user must have access to `/var/run/docker.sock`.
- **Usage:**
  ```bash
  eval "$(.venv/bin/python scripts/start_test_postgres.py --print-export)"
  .venv/bin/python scripts/check_postgres_validation.py
  ```

### `scripts/backfill_broker_position_protective_orders.py`
Backfills broker-neutral protective order evidence from stored broker bracket payload legs.

- **Use case:** After adding protective-order fields or importing older broker-position records, populate stop-loss/take-profit child order ids, statuses, prices, verification timestamp, and source from raw broker payloads where the broker exposes bracket legs.
- **Usage:**
  ```bash
  .venv/bin/python scripts/backfill_broker_position_protective_orders.py \
    --report-output artifacts/protective-order-backfill.json
  ```
- **Dry run:**
  ```bash
  .venv/bin/python scripts/backfill_broker_position_protective_orders.py --dry-run
  ```

### `scripts/report_stale_broker_positions.py`
Reports app broker-position ledger rows that are unsafe for steering mutation because they are expired, quantity-zero submitted rows, missing active protective evidence, or have stale protective-order verification.

- **Use case:** Run before enabling broker-position steering mutation and after reconciliation/backfill work.
- **Usage:**
  ```bash
  .venv/bin/python scripts/report_stale_broker_positions.py \
    --json-output artifacts/stale-broker-positions.json \
    --csv-output artifacts/stale-broker-positions-review.csv
  ```

### `scripts/mark_stale_broker_positions_needs_review.py`
Marks expired app broker-position ledger rows as `needs_review` after operator review. It is dry-run by default and never marks positions closed/win/loss without broker fill evidence.

- **Dry run:**
  ```bash
  .venv/bin/python scripts/mark_stale_broker_positions_needs_review.py \
    --reason "stale app ledger; broker confirmation unavailable"
  ```
- **Apply after review:**
  ```bash
  .venv/bin/python scripts/mark_stale_broker_positions_needs_review.py \
    --reason "stale app ledger; broker confirmation unavailable" \
    --apply
  ```

### `scripts/report_steering_dry_run_quality.py`
Builds a JSON summary and optional CSV review queue for broker-position steering dry-run decisions.

- **Use case:** Review steering quality before enabling any broker mutation path. It reports threshold status, decision counts, ticker concentration, reason-code frequencies, suspicious samples, recent close-now samples, recent amendment samples, and random review samples.
- **Usage:**
  ```bash
  .venv/bin/python scripts/report_steering_dry_run_quality.py \
    --json-output artifacts/steering-dry-run-quality.json \
    --csv-review-output artifacts/steering-dry-run-review-queue.csv
  ```
- **Review labels:** `correct`, `too_aggressive`, `too_conservative`, `bad_data`, `unclear`.
- **Rule:** Passing dry-run count thresholds is not enough; close-now and amendment samples must be reviewed before setting `steering_dry_run=false`.

### `scripts/check_etoro_release_readiness.py`
Runs the multi-broker/eToro release readiness checklist before any eToro live micro-size rollout.

- **Use case:** Fail closed unless required external evidence exists and the local broker/risk validation suite passes.
- **Required artifact environment variables for a real release:**
  - `ETORO_READONLY_VALIDATION_ARTIFACT_ID`
  - `ETORO_DEMO_VALIDATION_ARTIFACT_ID`
  - `ETORO_LIVE_SHADOW_EVIDENCE_ID`
- **Behavior:** Runs the default pytest suite, focused broker/eToro risk tests, migration tests, broker migration/backfill smoke validation, optional Postgres validation via `scripts/check_postgres_validation.py`, and frontend type checks when `frontend/package.json` exists. Postgres validation now checks upgrade-to-head on a clean schema, broker-account tables, account-scoped columns, safety tables, and the default Alpaca paper account after upgrade. Data-dependent Postgres recomputation tests are opt-in with `POSTGRES_VALIDATION_INCLUDE_DATA_TESTS=1` because they require a restored database containing historical recommendation plan ids 315 and 635.
- **Usage:**
  ```bash
  ETORO_READONLY_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_LIVE_SHADOW_EVIDENCE_ID=<id> \
    .venv/bin/python scripts/check_etoro_release_readiness.py
  ```
- **Write release-readiness report:**
  ```bash
  ETORO_READONLY_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_LIVE_SHADOW_EVIDENCE_ID=<id> \
    .venv/bin/python scripts/check_etoro_release_readiness.py \
      --report-output artifacts/etoro-release-readiness.json
  ```
  The JSON report records artifact ids, validation commands/results, missing artifacts, and live micro-size defaults.
- **Local dry-run only:**
  ```bash
  .venv/bin/python scripts/check_etoro_release_readiness.py \
    --dry-run \
    --allow-missing-external-artifacts \
    --report-output artifacts/local-etoro-readiness-dry-run.json
  ```
  Do not use `--allow-missing-external-artifacts` for a real release.

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
