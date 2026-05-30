# Fundamental analysis snapshot implementation plan

**Status:** active plan

Concrete implementation plan for `fundamental-analysis-snapshot-spec.md`.

## Objective

Ship monthly and event-aware point-in-time fundamental snapshots for monitored tickers, then expose those snapshots to ticker analysis and plan generation with a conservative decision role.

Success means:
- every active watchlist ticker and app-owned broker-exposure ticker can get a stored immutable fundamental snapshot
- snapshots can be refreshed by job/manual path
- ticker analysis/plan payloads include the latest snapshot known at plan time
- fundamentals do not positively boost confidence until validation proves value
- validation slices can measure whether snapshot features improve outcomes

## Phase 0 — design and fixtures

Status: started. Target-behavior contract tests now live in `tests/test_fundamental_analysis_snapshots.py` and are marked strict xfail until implementation phases make them pass.

Deliverables:
- finalize normalized snapshot payload keys
- add compact provider fixture payloads for tests
- identify monitored ticker source query

Normalized payload shape:
```json
{
  "business_profile": {},
  "valuation": {},
  "profitability_quality": {},
  "growth": {},
  "balance_sheet_risk": {},
  "cash_flow": {},
  "analyst_context": {},
  "event_calendar": {},
  "feature_buckets": {},
  "provider_diagnostics": {},
  "raw_payload_refs": {}
}
```

Acceptance:
- fixtures include full, partial, and failed-provider examples
- payload schema is documented in tests and raw-details reference when implemented

## Phase 1 — persistence

Add table `fundamental_analysis_snapshots`.

Columns:
- `id`
- `ticker` indexed
- `as_of` indexed
- `source_set_json`
- `coverage_status`
- `freshness_status`
- `payload_json`
- `warnings_json`
- `missing_inputs_json`
- `job_id`, `run_id`
- timestamps

Repository methods:
- `create_snapshot(snapshot)`
- `get_latest_for_ticker(ticker)`
- `get_latest_at_or_before(ticker, as_of)`
- `list_latest_by_tickers(tickers, as_of=None)`
- `list_stale_monitored_tickers(monitored_tickers, stale_before)`

Tests:
- immutable create and round-trip
- latest by ticker
- point-in-time lookup excludes future snapshots
- stale ticker discovery
- JSON decoding survives malformed/empty values

Validation:
- migration tests
- repository tests

## Phase 2 — monitored ticker discovery

Create `MonitoredTickerService` or small repository helper.

Ticker sources:
- active watchlist tickers
- broker positions with active exposure, including `submitted`, `open`, `closing`
- active broker orders with submitted/pending statuses

Rules:
- uppercase/deduplicate
- ignore blank/malformed tickers
- return provenance: `watchlist`, `broker_order`, `broker_position`

Tests:
- watchlist-only discovery
- broker-only discovery
- dedupe and provenance merge
- closing positions count as monitored exposure

## Phase 3 — fundamental analysis service

Add `src/trade_proposer_app/services/fundamental_analysis.py`.

Responsibilities:
- fetch provider data for one ticker
- normalize into snapshot payload
- classify feature buckets
- compute event-aware refresh hints
- degrade safely on provider errors/missing fields

Initial provider:
- yfinance-derived data is acceptable for v1, but diagnostics must mark provider limitations
- no network calls in unit tests; use fake provider/client fixtures

Core methods:
- `analyze(ticker, as_of=None) -> FundamentalAnalysisSnapshot`
- `refresh_ticker(ticker, job_id=None, run_id=None, as_of=None)`
- `snapshot_due_reason(latest_snapshot, as_of)`
- `important_event_window(snapshot, as_of)`

Feature buckets:
- valuation: `low`, `medium`, `high`, `unknown` relative to sector when possible, otherwise absolute fallback with warning
- profitability_quality: `weak`, `average`, `strong`, `unknown`
- growth: `negative`, `flat`, `positive`, `high`, `unknown`
- balance_sheet_risk: `low`, `medium`, `high`, `unknown`
- event_regime: `none_known`, `pre_event`, `event_week`, `post_event`, `stale_event`, `unknown`

Tests:
- complete provider data maps to normalized payload
- partial data marks missing inputs but still creates degraded snapshot
- provider failure creates blocked/degraded snapshot without crashing job
- event windows are classified correctly around earnings/shareholder dates
- no positive confidence contribution is emitted

## Phase 4 — refresh job

Add job type: `fundamental_analysis_refresh`.

Default schedule:
- monthly baseline job, e.g. `15 07 1 * *`
- optional daily lightweight due-check job later if event-aware refresh needs frequent evaluation

Job behavior:
- discover monitored tickers
- refresh if latest snapshot older than 30 days
- refresh if important event window requires it
- cap per-run ticker count to avoid provider abuse
- persist run summary with counts: refreshed, skipped_fresh, failed, monitored_count

Manual/API path:
- run all due monitored tickers
- run specific ticker refresh

Tests:
- job executes due tickers only
- monthly staleness works
- event window overrides monthly freshness
- provider failures do not fail entire run unless all fail catastrophically
- run artifact contains per-ticker statuses

## Phase 5 — analysis and plan integration

Inject latest point-in-time snapshot into:
- `TickerDeepAnalysisService` context
- watchlist signal snapshot source breakdown/diagnostics
- recommendation plan `signal_breakdown`
- recommendation plan `evidence_summary`
- raw details reference

Rules:
- use `get_latest_at_or_before(ticker, plan_as_of)`
- missing snapshot adds `fundamental_snapshot_missing` warning only; it does not block plans in v1
- stale snapshot adds caution warning
- upcoming earnings/shareholder event inside holding window adds event-window warning and may raise action threshold only in a fixed conservative way if specified by policy
- no positive confidence boost

Suggested compact payload keys:
- `fundamental_snapshot_id`
- `fundamental_snapshot_as_of`
- `fundamental_coverage_status`
- `fundamental_event_regime`
- `fundamental_warnings`
- `fundamental_feature_buckets`
- `next_known_event`

Tests:
- plan uses prior snapshot, not future snapshot
- missing snapshot remains non-blocking
- stale/degraded snapshot warning is surfaced
- event inside holding period is included in evidence/diagnostics
- confidence does not increase because of fundamentals

## Phase 6 — UI and observability

UI surfaces:
- ticker page: latest snapshot card
- recommendation plan raw/details: compact fundamental context
- settings/debugger/data quality: stale monitored tickers and provider errors

Observability events:
- `fundamental_refresh_started`
- `fundamental_snapshot_created`
- `fundamental_refresh_failed`
- `fundamental_refresh_completed`

Tests:
- route returns latest snapshot
- route triggers manual refresh with fake service
- UI typecheck updated types

## Phase 7 — validation and research slices

Add fundamental slices to reliability/research summaries after snapshots exist in plan payloads.

Slices:
- event regime
- earnings within 3/7/14 days
- analyst action/recommendation bucket
- valuation bucket
- profitability/quality bucket
- growth bucket
- balance-sheet-risk bucket
- setup family + event regime

Metrics:
- broker-preferred effective win rate
- expected value when available
- false-positive reduction
- loss streak/drawdown behavior
- entry-touch/no-entry behavior

Acceptance:
- slices show resolved counts and sparse-data warnings
- no promotion of fundamental positive boosts without walk-forward evidence
- docs explain which slices are exploratory vs action-affecting

## Rollout order

Recommended commits:
1. spec/docs + fixtures
2. migration/domain/repository
3. monitored ticker discovery
4. fundamental service with fake-provider tests
5. job/manual route
6. analysis/plan integration with no confidence boost
7. UI/raw details
8. validation slices

## Safety gates

Before enabling any action-affecting use:
- at least 30 days of passive snapshots
- enough resolved broker-preferred outcomes per slice
- walk-forward validation beats baseline
- no increase in drawdown/loss streak
- operator-visible sparse evidence warnings

Initial shipped mode must be passive/conservative:
- collect snapshots
- display and persist context
- warn/raise caution around event risk
- do not boost confidence
