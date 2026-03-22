# Shared Sentiment Snapshot Implementation Plan

This document breaks the shared-snapshot refactor into concrete code changes for Trade Proposer App.

## Objective

Refactor the current hierarchical sentiment pipeline so that:
- macro sentiment is computed by scheduled shared jobs
- industry sentiment is computed by scheduled shared jobs
- ticker sentiment remains live during proposal generation
- proposal generation reuses the latest valid macro and industry snapshots

## File-by-file plan

### 1. Domain and persistence

#### `src/trade_proposer_app/domain/models.py`
Add a new domain model:
- `SentimentSnapshot`

Suggested fields:
- `id`
- `scope`
- `subject_key`
- `subject_label`
- `status`
- `score`
- `label`
- `computed_at`
- `expires_at`
- `coverage_json`
- `source_breakdown_json`
- `drivers_json`
- `signals_json`
- `diagnostics_json`
- `job_id`
- `run_id`

#### `src/trade_proposer_app/persistence/models.py`
Add a new SQLAlchemy record:
- `SentimentSnapshotRecord`

Include indexes on:
- `scope`
- `subject_key`
- `computed_at`
- `expires_at`

#### `alembic/versions/*`
Add a migration to create the snapshots table.

### 2. Repository layer

#### `src/trade_proposer_app/repositories/sentiment_snapshots.py`
Create a repository with methods like:
- `create_snapshot(...)`
- `get_latest_snapshot(scope, subject_key)`
- `get_latest_valid_snapshot(scope, subject_key, now)`
- `list_recent_snapshots(scope=None)`
- `delete_snapshot(id)` optional later

### 3. Services for shared refresh workflows

#### `src/trade_proposer_app/services/macro_sentiment.py`
Create `MacroSentimentService`.

Responsibilities:
- define macro query set
- fetch signals from news/social providers
- compute macro sentiment
- compute diagnostics and coverage
- persist `SentimentSnapshot`

#### `src/trade_proposer_app/services/industry_sentiment.py`
Create `IndustrySentimentService`.

Responsibilities:
- resolve industries from taxonomy
- build per-industry query sets
- fetch news/social signals
- compute industry sentiment
- persist `SentimentSnapshot`

#### `src/trade_proposer_app/services/snapshot_resolver.py`
Create a small resolver service.

Responsibilities:
- fetch the latest valid macro snapshot
- fetch the latest valid industry snapshot for a ticker
- determine stale/missing state
- return neutral fallbacks + warnings if unavailable

### 4. Job execution integration

#### `src/trade_proposer_app/domain/enums.py`
Add new job types:
- `MACRO_SENTIMENT_REFRESH`
- `INDUSTRY_SENTIMENT_REFRESH`

#### `src/trade_proposer_app/services/job_execution.py`
Extend the job execution path to support the two new workflow types.

#### `src/trade_proposer_app/services/runs.py`
Update any run summary handling so the new workflows produce auditable run outputs.

#### `src/trade_proposer_app/workers/tasks.py`
Ensure worker task dispatch supports the new workflow services.

### 5. Proposal service refactor

#### `src/trade_proposer_app/services/proposals.py`
Refactor so proposal generation:
- no longer computes macro/industry sentiment inline as the primary source
- instead loads them from snapshot resolver
- keeps ticker sentiment live
- fuses:
  - macro snapshot
  - industry snapshot
  - live ticker sentiment

Update `analysis_json` so:
- `sentiment.macro.source = "snapshot"`
- `sentiment.industry.source = "snapshot"`
- `sentiment.ticker.source = "live"`
- snapshot identifiers and freshness metadata are persisted

### 6. Builders and app composition

#### `src/trade_proposer_app/services/builders.py`
Wire up:
- snapshot repository
- snapshot resolver
- macro refresh service
- industry refresh service
- proposal service with snapshot dependencies

### 7. Health and preflight

#### `src/trade_proposer_app/services/preflight.py`
Add checks for:
- sentiment snapshot table availability after migration
- taxonomy readability
- optional snapshot freshness summary later

### 8. API routes

#### `src/trade_proposer_app/api/routes/*`
Add routes for:
- listing recent macro snapshots
- listing recent industry snapshots
- inspecting a snapshot by id
- optional manual refresh endpoint later

Possible new file:
- `src/trade_proposer_app/api/routes/sentiment_snapshots.py`

### 9. Frontend

#### `frontend/src/*`
Add views/cards for:
- latest macro snapshot
- latest industry snapshots
- freshness status
- snapshot diagnostics

Proposal/run detail views should show:
- macro snapshot used
- industry snapshot used
- live ticker sentiment
- combined overall sentiment

### 10. Docs

Update:
- `README.md`
- `docs/architecture.md`
- `docs/features-and-capabilities.md`
- `docs/raw-details-reference.md`
- `docs/phase-2-app-native.md`

Add references to:
- shared sentiment snapshots
- refresh workflows
- snapshot-backed proposal fusion

## Delivery phases

### Phase A — Persistence and repository
- add `SentimentSnapshot` models
- add DB migration
- add repository

### Phase B — Macro refresh service
- implement macro queries
- persist macro snapshots
- support scheduled refresh job

### Phase C — Industry refresh service
- implement taxonomy-driven industry refresh
- persist industry snapshots
- support scheduled refresh job

### Phase D — Proposal consumption
- proposal service reads snapshots
- snapshot metadata added to `analysis_json`
- warnings for stale/missing snapshots

### Phase E — UI and docs
- snapshot inspection UI
- run detail integration
- documentation refresh

## Recommended first coding pass

If implemented incrementally, start with:
1. domain + persistence model
2. repository
3. macro refresh workflow
4. proposal service reading macro snapshot only
5. industry snapshot workflow next

This keeps the migration small and reduces the blast radius.

## Testing plan

### Unit tests
- snapshot repository CRUD and latest-valid lookup
- snapshot resolver stale/missing behavior
- macro refresh scoring and persistence
- industry refresh scoring and persistence

### Integration tests
- proposal run with fresh snapshots
- proposal run with stale snapshots
- proposal run with missing snapshots
- worker execution of macro and industry refresh jobs

### Regression tests
- proposal generation still works when no snapshots exist
- diagnostics clearly explain neutral fallback behavior

## Acceptance criteria

The refactor is complete when:
- macro sentiment is no longer recomputed inline for each ticker as the primary source
- industry sentiment is no longer recomputed inline for each ticker as the primary source
- proposal generation reuses shared snapshots
- ticker sentiment remains live
- missing snapshots produce explicit neutral diagnostics
- the UI and stored payloads clearly identify snapshot-backed sentiment layers
