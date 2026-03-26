# Data Model and Persistence

## Database direction

The redesigned app should use a proper database, with PostgreSQL as the target datastore.

### Why PostgreSQL

- reliable production persistence
- strong relational modeling
- JSONB support for structured diagnostics and evidence payloads
- indexing for time-based and entity-based queries
- good migration support
- suitable for analytics, evaluation, and backtesting

## What must be stored

The system should store at least:

- raw ingested source items
- ingestion diagnostics and failures
- normalized detected events
- evidence links between events and source items
- macro context snapshots
- industry context snapshots
- ticker signal snapshots
- recommendation plans
- recommendation outcomes

## Schema direction

### `source_items`
Raw ingested content.

Suggested fields:

- id
- source_type (`news`, `social`, `official`)
- provider
- title
- body
- url
- author
- published_at
- ingested_at
- dedupe_hash
- metadata JSONB

### `source_item_fetches`
Diagnostics for ingestion attempts.

Suggested fields:

- id
- provider
- started_at
- finished_at
- status
- item_count
- warning_messages JSONB
- error_message
- metadata JSONB

### `detected_events`
Normalized events.

Suggested fields:

- id
- scope (`macro`, `industry`, `ticker`)
- event_key
- label
- direction
- saliency_score
- confidence_score
- novelty_score
- started_at
- detected_at
- metadata JSONB

### `event_evidence`
Join table between events and evidence.

Suggested fields:

- event_id
- source_item_id
- evidence_weight

### `macro_context_snapshots`
Suggested fields:

- id
- computed_at
- status
- summary_text
- saliency_score
- confidence_score
- active_themes JSONB
- regime_tags JSONB
- warnings JSONB
- missing_inputs JSONB
- source_breakdown JSONB
- metadata JSONB

### `industry_context_snapshots`
Suggested fields:

- id
- industry_key
- computed_at
- status
- summary_text
- direction
- saliency_score
- confidence_score
- active_drivers JSONB
- linked_macro_themes JSONB
- linked_industry_themes JSONB
- warnings JSONB
- missing_inputs JSONB
- source_breakdown JSONB
- metadata JSONB

### `ticker_signal_snapshots`
Suggested fields:

- id
- ticker
- computed_at
- status
- direction
- swing_probability
- confidence_score
- setup_family
- macro_exposure_score
- industry_alignment_score
- ticker_sentiment_score
- technical_setup_score
- catalyst_score
- expected_move_score
- execution_quality_score
- confidence_components JSONB
- warnings JSONB
- missing_inputs JSONB
- metadata JSONB

### `recommendation_plans`
Suggested fields:

- id
- ticker
- created_at
- status
- direction
- entry_low
- entry_high
- stop_loss
- take_profit
- horizon_days
- confidence_score
- risk_reward_ratio
- thesis_text
- risks JSONB
- warnings JSONB
- evidence_summary JSONB
- metadata JSONB

For redesign-native workflows, `recommendation_plans` should be treated as the canonical trade-planning object. Legacy `Recommendation` rows may still be emitted as compatibility projections, but they should not be the primary persistence target for redesigned proposal flows.

### `recommendation_outcomes`
Suggested fields:

- recommendation_plan_id
- resolved_at
- outcome
- pnl_pct
- horizon_return_1d
- horizon_return_3d
- horizon_return_5d
- max_favorable_excursion
- max_adverse_excursion
- realized_holding_period_days
- direction_correct
- confidence_bucket
- setup_family
- notes

## Diagnostics as first-class data

Warnings and failures should not be stored only in logs.

The database should preserve:

- source failures
- missing inputs
- degraded reasons
- confidence caps
- suppression reasons
- evidence counts
- source breakdowns

This supports auditability, debugging, and user trust.

## Shared status model

Every major object should expose a structured status field:

- `ok`
- `partial`
- `degraded`
- `failed`

This should apply to:

- ingestion runs
- context snapshots
- ticker signal snapshots
- recommendation plans

## Why persistence matters

A proper database is required not only for current state, but also for:

- historical comparison
- evaluation of recommendation quality
- backtesting and outcome analysis
- detecting repeated event patterns
- understanding why past recommendations succeeded or failed
