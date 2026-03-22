# Raw Details Reference

Trade Proposer App persists diagnostic metadata alongside runs, recommendations, and sentiment refresh workflows so operators can audit behavior without leaving the platform.

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
- `macro`: snapshot-backed shared macro sentiment, including `snapshot_id`, `subject_key`, `label`, `score`, and source/freshness metadata
- `industry`: snapshot-backed shared industry sentiment, including `snapshot_id`, `subject_key`, `label`, `score`, and source/freshness metadata
- `ticker`: live per-proposal ticker sentiment
- `enhanced`: the fused sentiment result used by the scoring logic, plus component contributions
- `coverage_insights` / `keyword_hits`: transparency fields for sparse or neutral sentiment coverage

The UI uses the stored `snapshot_id` values to link runs and recommendations back to the exact shared snapshot records that influenced them.

### Other stored payloads
- `raw_output`: scripted stdout/stderr or raw pipeline detail when available
- `feature_vector_json`: technical feature values before normalization
- `normalized_feature_vector_json`: the normalized version used by the weights
- `aggregations_json`: intermediate aggregate metrics such as momentum, volatility, or trend scores
- `confidence_weights_json`: per-feature weights loaded from `weights.json`
- `summary_method`: how the summarization backend generated the narrative

## Recommendation-specific fields

Recommendations persist the execution-facing trade object:
- `direction`: `LONG`, `SHORT`, or `NEUTRAL`
- `confidence`: floating-point score in `[0, 1]`
- `entry_price`
- `stop_loss`
- `take_profit`
- `indicator_summary`

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
- **Diagnostics reuse**: the same stored payloads support the debugger, run detail pages, recommendation detail pages, ticker pages, and `/api/health`.
