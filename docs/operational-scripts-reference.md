# Operational Scripts Reference

**Status:** reference

This document lists the standalone scripts available in the `scripts/` directory for maintenance, hydration, and regression testing.

For evidence repair, tuning, phantom selectivity, upstream signal-quality audits, and prospective monitoring, use `evidence-and-tuning-operations-runbook.md` as the workflow. This reference lists the script entry points; the runbook defines ordering, verdicts, gates, and stop/go decisions.

## Evidence, tuning, and upstream quality scripts

These scripts are read-only unless explicitly documented otherwise. Run database-backed evidence scripts inside the API container unless a local database URL is configured:

```bash
docker compose exec -T api sh -lc 'python scripts/<script>.py ...'
```

### `scripts/monitor_upstream_signal_driver_tags.py`
Monitors prospectively emitted `signal_breakdown.upstream_signal_quality_drivers` tags on stored plans.

- **Use case:** Standing checkpoint while the tuning layer is on hold. Reports whether tagged evidence is absent, accumulating, or ready for review.
- **Default artifact:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/monitor_upstream_signal_driver_tags.py \
    --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-tag-monitor-latest.json'
  ```
- **Read first:** `docs/evidence-and-tuning-operations-runbook.md`.

### `scripts/audit_evidence_lineage.py`
Compares prospective tag freshness with replay eligibility freshness.

- **Use case:** Explain whether new tagged plans are entering the phantom-selectivity replay path, or whether replay eligibility is stale, filtered, or missing.
- **Example:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/audit_evidence_lineage.py \
    --replay-tier tier_a \
    --artifact /app/.prod-run/workers/artifacts/evidence-lineage-latest.json'
  ```
- **Read first:** `docs/evidence-and-tuning-operations-runbook.md`.

### `scripts/recover_recommendation_plan_evaluations.py`
Recovers missing recommendation plan outcome rows through explicit, bounded chunks.

- **Use case:** Catch up evaluation evidence after scheduler starvation or operator-requested recovery without changing jobs, tuning config, broker settings, or orders.
- **Behavior:** Selects missing outcome rows first, can prioritize prospectively tagged plans, commits each chunk, and can write a progress artifact.
- **Dry run:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/recover_recommendation_plan_evaluations.py --dry-run'
  ```
- **Tagged recovery:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/recover_recommendation_plan_evaluations.py \
    --only-tagged \
    --artifact /app/.prod-run/workers/artifacts/recommendation-evaluation-recovery.json'
  ```
- **Full missing-outcome recovery:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/recover_recommendation_plan_evaluations.py \
    --artifact /app/.prod-run/workers/artifacts/recommendation-evaluation-recovery.json'
  ```

### `scripts/audit_phantom_selectivity_separability.py`
Audits whether `phantom_win` rows are separable from `phantom_loss` rows before candidate replay.

- **Use case:** Decide whether phantom selectivity has candidate groups worth replaying, or whether this layer should stop.
- **Example:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/audit_phantom_selectivity_separability.py \
    --replay-tier tier_a \
    --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json'
  ```

### `scripts/replay_phantom_selectivity_candidates.py`
Replays separability candidate groups as if the candidate policy had emitted them as trades.

- **Use case:** Decide whether a phantom-selectivity lead remains research-only or has enough time-spread evidence for promotion preflight.
- **Example:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/replay_phantom_selectivity_candidates.py \
    --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
    --replay-tier tier_a \
    --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-candidate-replay-latest.json'
  ```

### `scripts/audit_upstream_signal_drivers.py`
Audits reusable upstream signal features behind phantom-selectivity candidate groups.

- **Use case:** Decide whether candidate lift is explained by reusable signal features or mostly ticker identity.
- **Example:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/audit_upstream_signal_drivers.py \
    --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
    --replay-tier tier_a \
    --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-audit-latest.json'
  ```

### `scripts/drilldown_upstream_signal_drivers.py`
Drills into concrete upstream feature/value drivers with examples and concentration checks.

- **Use case:** Inspect whether upstream signal leads are reusable enough to instrument or change generation code.
- **Example:**
  ```bash
  docker compose exec -T api sh -lc 'python scripts/drilldown_upstream_signal_drivers.py \
    --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
    --upstream-audit-artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-audit-latest.json \
    --replay-tier tier_a \
    --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-drilldown-latest.json'
  ```

### `scripts/large_plan_generation_parameter_search.py`
Runs bounded plan-generation tuning searches.

- **Use case:** Use only after evidence preflight says promotion or research conditions are valid. Do not use as the first step when evidence is thin.
- **Read first:** `docs/evidence-and-tuning-operations-runbook.md` and `docs/specs/large-parameter-search-spec.md`.

## Docker single-host deployment helpers

These scripts are optional helpers around the single `docker-compose.yml` deployment path. They require `.env.docker` to exist.

### `scripts/docker-up.sh`
Starts the Docker Compose stack.

```bash
scripts/docker-up.sh
```

Pass extra Compose arguments after the script name. Example worker scaling:

```bash
scripts/docker-up.sh --scale worker=2
```

Do not scale `scheduler` above one instance.

### `scripts/docker-down.sh`
Stops the Docker Compose stack.

```bash
scripts/docker-down.sh
```

### `scripts/docker-logs.sh`
Follows Docker Compose logs.

```bash
scripts/docker-logs.sh api worker scheduler
```

### `scripts/docker-backup.sh`
Creates a compressed custom-format Postgres backup under `./backups`.

```bash
scripts/docker-backup.sh
```

### `scripts/docker-restore-smoke.sh`
Restores a backup into a temporary Postgres database and runs Postgres validation.

```bash
scripts/docker-restore-smoke.sh backups/trade_proposer_YYYYMMDDTHHMMSSZ.dump
```

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

### `scripts/validate_bar_provider_quality.py`
Compares a candidate historical bar provider against the current Yahoo provider without writing canonical `historical_market_bars` rows.

- **Use case:** Weekly eToro bar-provider shadow validation. The script is read-only with respect to canonical bar storage.
- **Credential sources:** Prefer `ETORO_API_KEY` and `ETORO_USER_KEY` when they are present. If they are absent, the script falls back to the encrypted broker-account credential store using `--broker-account-id`, defaulting to `etoro-demo-main`.
- **Usage:**
  ```bash
  .venv/bin/python scripts/validate_bar_provider_quality.py \
    --tickers LRCX,CDNS,SNPS,AMAT,CRWD,PANW,FTNT,ZS,MDB,OKTA,TEAM,MTTR,SNOW,ADSK,PLTR,CVX,COP,OXY,SLB,HAL \
    --timeframe 1m \
    --days 5 \
    --artifact artifacts/etoro-vs-yahoo-1m.json
  ```

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
Runs the multi-broker/eToro release readiness checklist before any eToro demo default flip or future eToro live micro-size rollout.

- **Use case:** Fail closed unless required external evidence exists and the local broker/risk validation suite passes. During the eToro demo migration, use it to preserve the observed official OpenAPI version and keep Real mutation gates separate from demo work.
- **Live docs refresh before use:**
  ```bash
  curl -A 'Mozilla/5.0' -fsSL https://api-portal.etoro.com/llms.txt >/tmp/etoro-llms.txt
  curl -A 'Mozilla/5.0' -fsSL https://api-portal.etoro.com/api-reference/openapi.json \
    >/tmp/etoro-openapi.json
  python3 - <<'PY'
  import json
  print(json.load(open("/tmp/etoro-openapi.json"))["info"]["version"])
  PY
  ```
  Record the printed value with `--openapi-version` or `ETORO_OPENAPI_VERSION`.
- **Required artifact environment variables for a real release:**
  - `ETORO_READONLY_VALIDATION_ARTIFACT_ID`
  - `ETORO_DEMO_VALIDATION_ARTIFACT_ID`
  - `ETORO_DEMO_LIFECYCLE_ARTIFACT_ID`
  - `ETORO_LIVE_SHADOW_EVIDENCE_ID`
- **Behavior:** Runs the default pytest suite, focused broker/eToro risk tests, migration tests, broker migration/backfill smoke validation, optional Postgres validation via `scripts/check_postgres_validation.py`, and frontend type checks when `frontend/package.json` exists. Postgres validation now checks upgrade-to-head on a clean schema, broker-account tables, account-scoped columns, safety tables, and the default Alpaca paper account after upgrade. Data-dependent Postgres recomputation tests are opt-in with `POSTGRES_VALIDATION_INCLUDE_DATA_TESTS=1` because they require a restored database containing historical recommendation plan ids 315 and 635.
- **Usage:**
  ```bash
  ETORO_READONLY_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_LIFECYCLE_ARTIFACT_ID=<id> \
  ETORO_LIVE_SHADOW_EVIDENCE_ID=<id> \
    .venv/bin/python scripts/check_etoro_release_readiness.py
  ```
- **Write release-readiness report:**
  ```bash
  ETORO_READONLY_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_VALIDATION_ARTIFACT_ID=<id> \
  ETORO_DEMO_LIFECYCLE_ARTIFACT_ID=<id> \
  ETORO_LIVE_SHADOW_EVIDENCE_ID=<id> \
    .venv/bin/python scripts/check_etoro_release_readiness.py \
      --openapi-version v1.311.0 \
      --report-output artifacts/etoro-release-readiness.json
  ```
  The JSON report records artifact ids, validation commands/results, missing artifacts, observed OpenAPI version, expected OpenAPI version, and live micro-size defaults.
- **Local dry-run only:**
  ```bash
  .venv/bin/python scripts/check_etoro_release_readiness.py \
    --dry-run \
    --allow-missing-external-artifacts \
    --openapi-version v1.311.0 \
    --report-output artifacts/local-etoro-readiness-dry-run.json
  ```
  Do not use `--allow-missing-external-artifacts` for a real release.

### `scripts/validate_etoro_demo_integration.py`
Builds a redacted eToro Demo validation artifact from official demo endpoints.

- **Use case:** Validate eToro Demo credentials, read-only demo portfolio/P&L, symbol resolution, market rates, demo eligibility, demo what-if costs, and optionally a controlled demo order lifecycle. This script is demo-only and refuses to run when `ETORO_ENV` is not `demo`.
- **Credential variables:** Prefer `ETORO_DEMO_API_KEY` and `ETORO_DEMO_USER_KEY`. The script falls back to `ETORO_API_KEY` and `ETORO_USER_KEY` only when `ETORO_ENV=demo`.
- **Read/precheck validation artifact:**
  ```bash
  ETORO_ENV=demo \
  ETORO_DEMO_API_KEY=<demo-api-key> \
  ETORO_DEMO_USER_KEY=<demo-user-key> \
    .venv/bin/python scripts/validate_etoro_demo_integration.py \
      --symbol AAPL \
      --openapi-version v1.311.0 \
      --output artifacts/etoro-demo-validation.json
  ```
- **Controlled demo lifecycle artifact:** only use after reviewing the resolved instrument, current rates, eligibility, and cost response.
  ```bash
  ETORO_ENV=demo \
  ETORO_DEMO_API_KEY=<demo-api-key> \
  ETORO_DEMO_USER_KEY=<demo-user-key> \
    .venv/bin/python scripts/validate_etoro_demo_integration.py \
      --symbol AAPL \
      --amount-usd 25 \
      --stop-loss-rate <rate> \
      --take-profit-rate <rate> \
      --submit-demo-order \
      --close-after-submit \
      --openapi-version v1.311.0 \
      --output artifacts/etoro-demo-lifecycle-validation.json
  ```
- **Rule:** Do not use Real credentials. The artifact redacts key-like payload fields, but the command environment is still sensitive.

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
Seeds or updates the canonical default watchlist pack and scheduled job set in the database.
- Proposal-generation jobs stay linked to the seeded watchlists by name.
- Regional bars refresh jobs (`Bars-APAC`, `Bars-EU`, `Bars-US`) derive their ticker list from the current regional watchlists at runtime, so rerunning the seed script keeps bars coverage aligned with watchlist changes.
- Also deploys the default evaluation, broker steering dry-run, performance assessment, gating severity, confidence calibration, and weekend fundamentals jobs so fresh deployments get the same 41-job default schedule described in `default-watchlists.md`.

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
