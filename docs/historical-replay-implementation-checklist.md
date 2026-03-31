# Historical Replay Implementation Checklist

**Status:** active implementation checklist

This document translates `historical-replay-backtesting-plan.md` into concrete work inside this repository.

It is intentionally codebase-specific.
It names the likely modules to extend, the order of work, and the MVP slice that should be implemented first.

---

## Scope of this checklist

This checklist covers:
- schema additions
- domain model additions
- repository additions
- new replay job types
- service boundaries
- evaluation outputs
- a phased build order tied to the current modular-monolith architecture

This checklist does **not** lock in final field names for every table or JSON payload.
It defines the implementation direction and minimum required capabilities.

## Current implementation status

Implemented in the repo now:
- `historical_replay` job type
- `HistoricalReplayBatch` and `HistoricalReplaySlice` domain models
- persistence tables and Alembic migration for replay batches/slices
- repository and service scaffolding for batch creation, daily-slice planning, queueing, and resolved explicit ticker universes
- API endpoints for create/list/detail/execute replay batches plus universe-preset discovery and batch market-data hydration
- worker/job-execution integration for replay slice runs
- replay run summaries/artifacts now include entry timing, provider, source tier, market-data coverage, and a clearly labeled dummy signal payload used only until the app-native signal pipeline is wired in
- `HistoricalMarketBar` domain model plus repository/persistence scaffolding for Phase 2 market replay inputs
- Yahoo-style free-provider daily-bar integration for research-grade market-data hydration
- curated explicit universe presets: `us_large_cap_top20_v1` and `eu_large_cap_top20_v1`
- `next_open` / `next_close` entry-timing support with `next_open` as the canonical default
- dummy replay signal scaffolding with explicit documentation that it is temporary and must be aligned to the app-native signal pipeline later

This means **Phase 1 is complete**, and **Phase 2 has crossed into working market-data input hydration**, while true replay signal generation and outcome evaluation remain open.

---

## Uncompromisable implementation rule

## The replay path must preserve point-in-time integrity by construction.

This must be true in code, not only in documentation.

Concretely:
- replay services must receive an explicit `as_of` timestamp
- repositories used for replay must support `available_at <= as_of` filtering
- outcome labeling must be computed in a separate step from signal generation
- replay provenance must be persisted alongside derived objects
- strict and approximate backtests must remain distinguishable in storage and reporting

If a feature cannot state when an input became available, that feature should not participate in strict replay mode.

---

## Current architecture anchor points

The implementation should extend, not bypass, the current architecture.

### Existing modules to reuse
- `src/trade_proposer_app/domain/enums.py`
- `src/trade_proposer_app/domain/models.py`
- `src/trade_proposer_app/persistence/models.py`
- `src/trade_proposer_app/repositories/`
- `src/trade_proposer_app/services/job_execution.py`
- `src/trade_proposer_app/services/runs.py`
- `src/trade_proposer_app/services/watchlist_orchestration.py`
- `src/trade_proposer_app/services/ticker_deep_analysis.py`
- `src/trade_proposer_app/services/macro_context.py`
- `src/trade_proposer_app/services/industry_context.py`
- `src/trade_proposer_app/services/evaluation_execution.py`
- `src/trade_proposer_app/api/routes/jobs.py`
- `src/trade_proposer_app/api/routes/runs.py`
- `src/trade_proposer_app/workers/tasks.py`

### Existing concepts to preserve
The replay path should emit or reuse the same families of objects already familiar in the app:
- `Run`
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`

Replay-specific infrastructure should exist to support those objects, not replace them with a disconnected research-only data model.

---

## Proposed new concepts

## 1. Replay batch
A top-level container for one historical research run.

Purpose:
- identify a historical experiment
- record date range and cadence
- distinguish strict vs research mode
- track data-source configuration and replay version

### Suggested fields
- `id`
- `name`
- `status`
- `mode` (`strict` or `research`)
- `universe_mode`
- `universe_preset`
- `tickers_json`
- `entry_timing`
- `price_provider`
- `price_source_tier`
- `bar_timeframe`
- `started_at`
- `completed_at`
- `as_of_start`
- `as_of_end`
- `cadence` (`daily`, later maybe `hourly` or `intraday`)
- `config_json`
- `summary_json`
- `artifact_json`
- `error_message`
- `created_at`
- `updated_at`

## 2. Replay slice or replay timestamp run
A concrete replay execution for one timestamp `T`.

Purpose:
- bind one historical `as_of` timestamp to a normal run-like execution
- support restarting, partial failures, and metrics per timestamp

### Suggested fields
- `id`
- `replay_batch_id`
- `run_id` nullable if we choose a separate execution model, otherwise use `Run` as the canonical execution identity
- `as_of`
- `status`
- `universe_size`
- `input_summary_json`
- `output_summary_json`
- `timing_json`
- `error_message`
- `created_at`
- `updated_at`

## 3. Historical raw input records
These store replayable inputs with point-in-time metadata.

MVP should begin with the minimum needed set:
- market bars
- news items
- macro calendar/events
- optional universe-membership history

Later additions:
- social items
- article-body archives
- alternative data

## 4. Replay provenance
Either as shared JSON blobs or dedicated columns, every replay-derived object should be able to say:
- what batch created it
- the replay timestamp
- strict vs research mode
- source-tier confidence
- methodology version

---

## Schema plan

## A. Extend enums

### File
- `src/trade_proposer_app/domain/enums.py`

### Additions
Add new job types, at minimum:
- `HISTORICAL_REPLAY`
- `HISTORICAL_REPLAY_EVALUATION` if evaluation is decoupled
- optionally `HISTORICAL_BACKFILL_INGEST` for raw archive imports

### Why
This lets the existing run system, worker, scheduler, and UI reason about replay work explicitly instead of hiding it behind generic proposal-generation runs.

---

## B. Add domain models

### File
- `src/trade_proposer_app/domain/models.py`

### Add models for MVP
- `HistoricalReplayBatch`
- `HistoricalReplaySlice`
- `HistoricalReplayConfig`
- `ReplayProvenance`
- `HistoricalMarketBar`
- `HistoricalNewsItem`
- `HistoricalMacroEvent`
- `HistoricalOutcomeLabel`

### Design rule
Use typed Pydantic models even if some fields are stored as JSON.
The repo has already moved toward typed nested payloads; replay should follow that pattern.

---

## C. Add persistence models

### File
- `src/trade_proposer_app/persistence/models.py`

### Minimum new tables for MVP

#### `historical_replay_batches`
Stores batch metadata.

#### `historical_replay_slices`
Stores one replay timestamp execution record per `as_of`.

#### `historical_market_bars`
Stores OHLCV bars plus provenance.

Suggested unique key:
- `(ticker, timeframe, bar_time)`

#### `historical_macro_events`
Stores release timestamps and event metadata.

#### `historical_news_items`
Can be deferred until Phase 3, but the shape should be planned now.

Suggested important columns:
- `external_id`
- `source`
- `published_at`
- `available_at`
- `title`
- `body_text`
- `link`
- `ticker_mapping_json`
- `industry_mapping_json`
- `metadata_json`
- `source_tier`
- `point_in_time_confidence`

### Optional but strongly recommended
Add replay provenance columns to generated objects, likely:
- `replay_batch_id`
- `replay_as_of`
- `replay_mode`

Candidate tables to extend later:
- `macro_context_snapshots`
- `industry_context_snapshots`
- `ticker_signal_snapshots`
- `recommendation_plans`
- `recommendation_outcomes`

This avoids mixing replay artifacts with live artifacts invisibly.

---

## D. Add Alembic migrations

### Files
- `alembic/versions/...`
- `src/trade_proposer_app/migrations.py` if needed by project migration wiring

### Migration ordering recommendation
1. add replay batch / slice tables
2. add historical market bars
3. add historical macro events
4. add replay provenance columns to downstream generated objects
5. add historical news tables
6. add social/archive tables later only after source strategy is settled

---

## Repository plan

## New repositories

### `repositories/historical_replay.py`
Responsibilities:
- create/update replay batches
- create/update replay slices
- query replay batches and per-slice status
- summarize progress and failures

### `repositories/historical_market_data.py`
Responsibilities:
- bulk upsert bars
- query bars up to `as_of`
- query windowed history for technical indicator calculation

### `repositories/historical_macro_events.py`
Responsibilities:
- ingest macro calendar/events
- retrieve events available at or before `as_of`

### `repositories/historical_news.py`
Phase 3+
Responsibilities:
- bulk upsert historical news items
- retrieve news available at or before `as_of`
- filter by ticker/industry relevance

### `repositories/historical_outcomes.py`
Responsibilities:
- persist outcome labels for replay-generated plans
- support horizon and excursion queries

---

## Existing repositories likely to extend

### `repositories/runs.py`
Needs to support replay job execution cleanly.
Potential additions:
- better artifact filtering for replay runs
- helper methods for linking runs to replay batches/slices

### `repositories/jobs.py`
Needs replay job configuration support if replay jobs become first-class user-managed jobs.

### `repositories/recommendation_plans.py`
May need query helpers for replay-generated plans by batch, mode, and `as_of`.

### `repositories/recommendation_outcomes.py`
Should support outcome queries scoped to replay artifacts without mixing them with live results accidentally.

---

## Service plan

## 1. Historical data ingestion services

### New services

#### `services/historical_market_data.py`
Responsibilities:
- load or backfill bars from providers/files
- normalize and upsert into `historical_market_bars`
- validate continuity and missingness

#### `services/historical_macro_data.py`
Responsibilities:
- ingest macro event calendar and release timestamps
- derive replayable macro-input windows for a given `as_of`

#### `services/historical_news_ingestion.py`
Phase 3+
Responsibilities:
- ingest news archives
- normalize timestamps
- map tickers/industries
- persist provenance and tier metadata

---

## 2. Replay input assembly services

### New services

#### `services/historical_replay_inputs.py`
Responsibilities:
- assemble all replay inputs for a single `as_of`
- enforce `available_at <= as_of`
- return a structured input bundle for downstream context and proposal generation

Suggested output components:
- universe members
- market snapshots
- technical features
- macro event bundle
- industry proxy bundle
- news bundle when available
- replay provenance summary

This should be the main guardrail service for point-in-time integrity.

---

## 3. Replay feature and context services

### New or adapted services

#### `services/historical_feature_engine.py`
Responsibilities:
- compute technical features from historical bars only
- compute sector/industry relative-strength features
- compute baseline market regime proxies

#### `services/historical_context_replay.py`
Responsibilities:
- drive macro and industry context creation for a replay timestamp
- adapt current context builders to historical inputs

### Existing services to adapt carefully
- `services/macro_context.py`
- `services/industry_context.py`
- `services/ticker_deep_analysis.py`
- `services/watchlist_orchestration.py`

### Preferred adaptation pattern
Avoid scattering `if replay_mode` everywhere.
Instead:
- create replay input adapters that satisfy what these services need
- centralize point-in-time filtering earlier in the pipeline

---

## 4. Replay orchestration service

### New service

#### `services/historical_replay.py`
Responsibilities:
- orchestrate one replay batch
- materialize slices for a date range
- execute one replay timestamp end-to-end
- persist replay metadata and summary artifacts

Suggested public methods:
- `create_batch(...)`
- `plan_slices(...)`
- `execute_slice(slice_id)`
- `execute_batch(batch_id)`
- `finalize_batch(batch_id)`

This should be the main domain service for historical replay.

---

## 5. Replay outcome evaluation service

### New service

#### `services/historical_replay_evaluation.py`
Responsibilities:
- compute realized future outcome labels for replay-generated plans
- keep generation and evaluation logically separate
- persist horizon returns and excursion metrics

This should reuse the spirit of `evaluation_execution.py`, but should not assume live-run timing semantics.

---

## Job execution integration

## `services/job_execution.py`

### Add replay job branches
Add execution paths for the new replay job types.

At minimum:
- `_execute_historical_replay_run`
- optionally `_execute_historical_replay_evaluation_run`

### Expected responsibilities
The replay branch should:
1. load the replay batch or slice configuration
2. assemble replay inputs for `as_of`
3. generate context snapshots and recommendation plans
4. persist run summaries and artifacts with replay provenance
5. update replay-slice status
6. optionally enqueue separate evaluation work

### Important rule
Do not overload normal proposal generation execution with hidden historical behavior.
Replay should be explicit in job type and run artifacts.

---

## API plan

## New routes

### Suggested files
- `src/trade_proposer_app/api/routes/historical_replay.py`
- register from `src/trade_proposer_app/api/router.py`

### MVP endpoints
- `POST /api/historical-replay/batches`
- `GET /api/historical-replay/batches`
- `GET /api/historical-replay/batches/{id}`
- `POST /api/historical-replay/batches/{id}/execute`
- `GET /api/historical-replay/slices/{id}`
- `GET /api/historical-replay/batches/{id}/results`

### Optional ingest endpoints later
- `POST /api/historical-replay/ingest/market-bars`
- `POST /api/historical-replay/ingest/news`

---

## Frontend plan

The frontend does not need full replay UX for the MVP, but some visibility is important.

### Minimum recommended UI
- replay batch list page
- replay batch detail page
- basic status/progress and result summary
- links to generated runs and recommendation plans

### Likely files
- `frontend/src/pages/` new replay pages
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/layout.tsx` navigation link later, not necessarily in MVP

### Recommendation
Start with API and persisted artifacts first.
Add operator-facing research views after the replay pipeline works end to end.

---

## MVP slice to build first

## MVP definition
A useful first slice should backtest without depending on historical tweets or full historical article archives.

### Inputs
- daily OHLCV bars
- benchmark bars
- sector/industry mapping already present in taxonomy
- macro event calendar
- derived technical indicators
- derived macro and industry proxy features

### Outputs
- replay batches and replay slices
- replay-generated context artifacts at least in simplified form
- replay-generated recommendation plans
- future outcome labels for standard horizons
- summary comparison against simple baselines

### What this MVP should prove
- the repo can run point-in-time replay end to end
- the methodology can be evaluated without leakage
- context proxies can be tested before news/social history is fully solved

---

## Recommended phase-by-phase build checklist

## Phase 0 — definitions and rails
- [ ] finalize replay timestamp semantics
- [ ] finalize strict vs research mode semantics
- [ ] finalize entry/exit timing assumptions
- [ ] finalize standard horizons and excursion labels
- [ ] define provenance payload shape shared across replay objects

## Phase 1 — schema and job skeleton
- [x] add replay job type enums
- [x] add `HistoricalReplayBatch` and `HistoricalReplaySlice` domain models
- [x] add replay batch/slice persistence tables
- [x] add repositories for replay batches/slices
- [x] add API endpoints for create/list/detail/execute replay batches
- [x] add replay branch in `JobExecutionService`

## Phase 2 — market-data replay MVP
- [x] add `historical_market_bars` table and repository
- [x] implement free-provider daily-bar ingestion service
- [x] implement replay input assembly for bars up to `as_of`
- [ ] implement technical indicator computation using only prior bars
- [ ] implement recommendation-plan generation for one replay slice
- [x] persist run summary/artifact with replay metadata

## Phase 3 — macro and industry proxy context
- [ ] add `historical_macro_events` table and repository
- [ ] ingest macro event calendar
- [ ] build replayable macro proxy feature bundle
- [ ] build replayable industry proxy feature bundle
- [ ] generate replay macro context snapshot
- [ ] generate replay industry context snapshot
- [ ] compare technical-only vs technical-plus-context outputs

## Phase 4 — replay outcome evaluation
- [ ] add historical outcome-label model/repository
- [ ] compute horizon returns and excursion metrics after `as_of`
- [ ] persist replay outcome labels
- [ ] connect replay results to existing recommendation-plan evaluation reporting where sensible
- [ ] generate first calibration and baseline comparison report

## Phase 5 — historical news
- [ ] add `historical_news_items` table and repository
- [ ] implement historical news ingestion with `published_at` and `available_at`
- [ ] add ticker/industry mapping for articles
- [ ] add replay news retrieval for `available_at <= as_of`
- [ ] adapt event extraction for historical news inputs
- [ ] integrate news into replay support/context generation

## Phase 6 — operator/research visibility
- [ ] add replay batch list/detail UI
- [ ] show progress, failures, and summary metrics
- [ ] show generated plans and outcomes scoped to a replay batch
- [ ] expose strict vs research mode clearly in the UI

## Phase 7 — social and forward archival
- [ ] decide feasible historical social sources
- [ ] add social ingest only if provenance is acceptable
- [ ] archive live raw inputs going forward with first-seen timestamps
- [ ] persist model/prompt/version info for generated summaries
- [ ] make future periods gold-standard replay windows

---

## Proposed file additions

## Likely new backend files
- `src/trade_proposer_app/repositories/historical_replay.py`
- `src/trade_proposer_app/repositories/historical_market_data.py`
- `src/trade_proposer_app/repositories/historical_macro_events.py`
- `src/trade_proposer_app/repositories/historical_news.py`
- `src/trade_proposer_app/repositories/historical_outcomes.py`
- `src/trade_proposer_app/services/historical_replay.py`
- `src/trade_proposer_app/services/historical_replay_inputs.py`
- `src/trade_proposer_app/services/historical_market_data.py`
- `src/trade_proposer_app/services/historical_macro_data.py`
- `src/trade_proposer_app/services/historical_feature_engine.py`
- `src/trade_proposer_app/services/historical_replay_evaluation.py`
- `src/trade_proposer_app/api/routes/historical_replay.py`

## Likely new test files
- `tests/test_historical_replay_repositories.py`
- `tests/test_historical_market_data.py`
- `tests/test_historical_replay_inputs.py`
- `tests/test_historical_replay_service.py`
- `tests/test_historical_replay_routes.py`
- `tests/test_historical_replay_evaluation.py`

---

## Minimal migration-safe implementation strategy

To reduce risk, implement replay in a way that minimally disturbs live workflows.

### Recommended approach
1. add replay tables first without modifying live plan/context tables
2. get a replay batch working that produces run artifacts and external reports
3. only after that, add replay provenance columns to generated live-domain tables if needed
4. integrate replay-generated context snapshots and plans into first-class tables once provenance boundaries are clear

This keeps the first slice easier to ship and test.

---

## Reporting and evaluation checklist

The first usable replay report should include:
- number of replay timestamps executed
- universe size statistics
- number of generated plans
- action mix
- horizon return summaries
- hit rate / stop-out / target-hit metrics
- max favorable and adverse excursion summaries
- confidence-bucket calibration
- comparison versus at least one simple baseline
- split by strict vs research mode

Later reports should add:
- setup-family slices
- context regime slices
- transmission bias slices
- source-tier robustness slices

---

## Open design questions to resolve before coding too far

- Should replay-generated `RecommendationPlan` rows live in the same table as live plans with provenance columns, or first live in replay-only storage?
- Should one replay slice map one-to-one to a normal `Run`, or should replay slices have their own execution identity and optionally link to runs?
- Do we want one historical replay job type that runs an entire batch, or one job type per slice generated by a coordinator?
- Which provider or file source will supply the first historical OHLCV and macro-event data for the MVP?
- What is the first acceptable universe definition for historical membership without introducing severe survivorship bias?

These should be answered early because they affect how much the replay path reuses current run and plan infrastructure.

---

## Recommended first implementation decision

For this repo, the safest first decision is:

### Use a dedicated replay batch/slice layer, but execute each slice through the existing `Run` system.

That gives us:
- worker/scheduler reuse
- familiar run summaries/artifacts
- explicit replay metadata
- easier operator visibility
- less architectural branching than inventing a second execution engine

It also keeps replay work aligned with the current modular monolith and existing operational tooling.

---

## Definition of done for the first shippable milestone

The first milestone is done when the app can:
1. create a replay batch for a historical date range
2. execute daily replay slices through the worker-backed run system
3. assemble only point-in-time-valid market and macro-proxy inputs for each slice
4. generate recommendation plans for those slices
5. compute realized future outcomes over standard horizons
6. persist summaries and artifacts with replay provenance
7. produce a report comparing those plans against at least one simple baseline

When that works, the project has a real historical replay foundation and can safely expand into news, richer context, and later social data.
