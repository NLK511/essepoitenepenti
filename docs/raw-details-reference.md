# Raw Details Reference

**Status:** technical reference

This document answers one question:
> what does the app store, and what do the main structured payloads contain?

Trade Proposer App stores diagnostic metadata alongside runs, recommendation plans, recommendation-plan outcomes, ticker signals, and the shared macro/industry refresh workflows.

## Structured pipeline payloads

The app-native pipeline emits a structured JSON object for each ticker it scores. This object is persisted as `analysis_json`.

### `analysis_json`
The main sections are:
- `metadata`: timestamps, version, and ticker
- `trade`: direction, confidence, entry, stop-loss, and take-profit
- `summary`: digest or LLM narrative text plus generation metadata such as method, backend, model, runtime, fallback text, and errors
- `news`: unified items, feed usage, feed errors, item counts, and keyword-sentiment diagnostics
- `signals`: normalized cross-source signal payloads when additional signal providers are enabled
- `social`: social/Nitter-focused diagnostics when enabled
- `sentiment`: stored sentiment layers and enhanced/fused sentiment metadata
- `context_flags`: boolean keyword/context tags
- `feature_vectors`: nested `raw` and `normalized` values
- `aggregations`, `confidence_weights`, and `aggregation_weights`: weighted breakdowns and applied weight maps
- `diagnostics`: problems, provider failures, and summary errors

### `analysis_json.sentiment`
This section mixes live ticker sentiment with shared support-snapshot inputs.

Typical shape:
- `macro`: shared macro support snapshot data with fields such as `snapshot_id`, `subject_key`, `label`, `score`, and freshness/source metadata; when available it may also carry `context_snapshot_id`, `context_summary`, `context_events`, `context_lifecycle`, and contradiction labels from the redesign-native macro context object
- `industry`: shared industry support snapshot data with the same kind of fields and optional context-object metadata
- `ticker`: live per-proposal ticker sentiment
- `enhanced`: the fused sentiment result used by scoring, plus component contributions
- `coverage_insights` / `keyword_hits`: transparency fields for sparse or neutral coverage

The UI uses stored `snapshot_id` and `context_snapshot_id` values to link runs and trade outputs back to the shared artifacts that influenced them.

### Other stored payloads
- `raw_output`: scripted stdout/stderr or raw pipeline detail when available
- `feature_vector_json`: technical feature values before normalization
- `normalized_feature_vector_json`: the normalized version used by the weights
- `aggregations_json`: intermediate aggregate metrics such as momentum, volatility, or trend scores
- `confidence_weights_json`: per-feature weights loaded from `weights.json`
- `summary_method`: how the summarization backend generated the narrative

## Redesign-native trade objects

The redesign path persists these main trade-review objects:
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`

Important stored fields include:
- context lifecycle metadata such as `event_lifecycle_summary`, `contradictory_event_labels`, and per-event `persistence_state` / `window_hint`
- industry-context ontology metadata such as `ontology_profile`, `sector_definition`, `ontology_relationships`, `matched_ontology_relationships`, and `taxonomy_source_mode`
- ticker-level relationship diagnostics such as `ticker_relationship_edges` and `matched_ticker_relationships` inside deep-analysis `transmission_analysis`
- the same ticker relationship fields now also propagate into recommendation-plan `signal_breakdown.transmission_summary` when deep analysis produced them
- matched relationship summaries can indirectly affect stored recommendation-plan explanation fields such as `action_reason_detail`, `rationale_summary`, `invalidation_summary`, and `risks`
- frontend relationship read-through cards are rendered from the same recommendation-plan transmission payload fields rather than from a separate backend endpoint
- governed taxonomy registries now live in `src/trade_proposer_app/data/taxonomy/themes.json`, `src/trade_proposer_app/data/taxonomy/macro_channels.json`, and `src/trade_proposer_app/data/taxonomy/transmission_channels.json`
- relationship payloads can now include readable labels like `target_label` and `channel_label` while still preserving governed canonical keys underneath
- ticker transmission fields such as `context_strength_percent`, `context_event_relevance_percent`, `contradiction_count`, `decay_state`, and `transmission_confidence_adjustment`
- recommendation-plan calibration fields such as `raw_confidence_percent`, `calibrated_confidence_percent`, `confidence_adjustment`, `effective_confidence_threshold`, and sample-status snapshots inside `calibration_review`
- recommendation-plan action reasons such as `context_transmission_headwind` and `context_transmission_contradiction`

## Run and workflow artifacts

Run-level artifacts vary by workflow type.

Examples:
- proposal generation: recommendation summaries and diagnostics
- evaluation: evaluation scope and result summary
- optimization: before/after fingerprint and backup metadata
- context refresh: created `snapshot_id` or `snapshot_ids`, scope, refresh summary, and any derived context snapshot ids

The run detail page uses these artifacts to render workflow-specific cards or link directly to created snapshots.

## Support snapshot records

Shared macro and industry refresh workflows persist `SupportSnapshot` records with fields such as:
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

These records are both reusable support-cache artifacts and audit objects.

## Diagnostics and timing fields

Common stored diagnostic fields include:
- `warnings`
- `provider_errors`
- `problems`
- `news_feed_errors`
- `summary_error` / `llm_error`
- `timing_json`
- `analysis_timestamp`

## Operational reference notes

- `weights.json` lives in `src/trade_proposer_app/data/` and is used for scoring runs.
- `/api/health/preflight` reports dependency readiness and shared support-snapshot freshness.
- operators configure the summary backend via `/settings` using `news_digest`, `openai_api`, or `pi_agent`.
- the same stored payloads support the debugger, run detail pages, recommendation-plan pages, ticker pages, and health views.

## See also

- `recommendation-methodology.md` — how the pipeline works
- `features-and-capabilities.md` — what the app can do now
- `operator-page-field-guide.md` — where those fields appear in the UI
