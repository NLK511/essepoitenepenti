# Raw Details Reference

Trade Proposer App persists diagnostic metadata alongside runs, redesign recommendation plans, and sentiment/context refresh workflows so operators can audit behavior without leaving the platform. `RecommendationPlan`, `RecommendationPlanOutcome`, context snapshots, and ticker-signal snapshots are the active operator workflow objects.

## Structured pipeline payloads

The app-native pipeline emits a structured JSON object for each ticker it scores. This object is persisted as `analysis_json`.

### `analysis_json`
The canonical structured payload groups diagnostics into a small number of logical sections:
- `metadata`: timestamps, version, and the ticker that the pipeline scored
- `trade`: direction, confidence, entry, stop-loss, and take-profit
- `summary`: digest or LLM narrative text plus generation metadata (`method`, `backend`, `model`, runtime, fallback text, and errors)
- `news`: unified `items`, feed usage, feed errors, item counts, and keyword-sentiment diagnostics
- `signals`: normalized cross-source signal payloads when additional signal providers are enabled
- `social`: social/Nitter-focused diagnostics when enabled
- `sentiment`: the stored sentiment layers and enhanced/fused sentiment metadata
- `context_flags`: boolean keyword/context tags
- `feature_vectors`: nested `raw` and `normalized` values
- `aggregations`, `confidence_weights`, and `aggregation_weights`: weighted breakdowns and applied weight maps
- `diagnostics`: problems, provider failures, and summary errors

### `analysis_json.sentiment`
This section is especially important because it now mixes live and snapshot-backed inputs.

Typical shape:
- `macro`: snapshot-backed shared macro sentiment, including `snapshot_id`, `subject_key`, `label`, `score`, and source/freshness metadata; when available it also carries `context_snapshot_id`, `context_summary`, `context_events`, `context_lifecycle`, and contradiction labels from the redesign-native macro context object
- `industry`: snapshot-backed shared industry sentiment, including `snapshot_id`, `subject_key`, `label`, `score`, and source/freshness metadata; when available it also carries `context_snapshot_id`, `context_summary`, `context_events`, `context_lifecycle`, and contradiction labels from the redesign-native industry context object
- `ticker`: live per-proposal ticker sentiment
- `enhanced`: the fused sentiment result used by the scoring logic, plus component contributions
- `coverage_insights` / `keyword_hits`: transparency fields for sparse or neutral sentiment coverage

The UI uses the stored `snapshot_id` and `context_snapshot_id` values to link runs and trade outputs back to the exact shared artifacts that influenced them.

### Other stored payloads
- `raw_output`: scripted stdout/stderr or raw pipeline detail when available
- `feature_vector_json`: technical feature values before normalization
- `normalized_feature_vector_json`: the normalized version used by the weights
- `aggregations_json`: intermediate aggregate metrics such as momentum, volatility, or trend scores
- `confidence_weights_json`: per-feature weights loaded from `weights.json`
- `summary_method`: how the summarization backend generated the narrative

## Trade-output-specific fields

The redesign path persists `RecommendationPlan` objects, `RecommendationPlanOutcome` objects, and `TickerSignalSnapshot` objects for watchlist orchestration. These redesign objects are the canonical place to inspect structured trade planning, per-ticker reasoning, and measured plan outcomes.

Important redesign-native fields now include:
- context snapshot lifecycle metadata such as `event_lifecycle_summary`, `contradictory_event_labels`, and per-event `persistence_state` / `window_hint`
- ticker transmission fields such as `context_strength_percent`, `context_event_relevance_percent`, `contradiction_count`, `decay_state`, and `transmission_confidence_adjustment`
- recommendation-plan calibration fields such as `raw_confidence_percent`, `calibrated_confidence_percent`, `confidence_adjustment`, `effective_confidence_threshold`, and slice-level sample-status snapshots inside `calibration_review`
- recommendation-plan action reasons such as `context_transmission_headwind` and `context_transmission_contradiction` when broader context blocks promotion

## Run and workflow artifacts

Run-level artifacts vary by workflow type.

Examples:
- proposal generation: recommendation summaries and diagnostics
- evaluation: evaluation scope and result summary
- optimization: before/after fingerprint and backup metadata
- sentiment refresh: created `snapshot_id` or `snapshot_ids`, scope, and refresh summary

The run detail page uses these artifacts to render workflow-specific cards or link directly to created snapshots.

## Sentiment snapshot records

Shared macro and industry refresh workflows persist `SentimentSnapshot` records with fields such as:
- `id`
- `scope`
- `subject_key`
- `subject_label`
- `status`
- `score`
- `label`
- `computed_at`
- `expires_at`
- `coverage`
- `source_breakdown`
- `drivers`
- `signals`
- `diagnostics`
- `job_id`
- `run_id`

These records act as both reusable cache and audit object.

## Diagnostics and timing

These fields help populate debugger, run detail, and health views:
- `warnings`
- `provider_errors`
- `problems`
- `news_feed_errors`
- `summary_error` / `llm_error`
- `timing_json`
- `analysis_timestamp`

## Operational notes

- **Weights**: `weights.json` lives in `src/trade_proposer_app/data/` and is used for every scoring run.
- **Preflight**: `/api/health/preflight` reports on dependency readiness and now also includes shared snapshot freshness checks, so the app can signal degraded sentiment context before proposal generation.
- **Summarization**: operators configure the summary backend via `/settings` (`news_digest`, `openai_api`, or `pi_agent`).
- **Diagnostics reuse**: the same stored payloads support the debugger, run detail pages, recommendation-plan and ticker pages, and `/api/health`.
