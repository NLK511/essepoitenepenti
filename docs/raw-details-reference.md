# Raw Details Reference

The Trade Proposer App persists rich diagnostic metadata alongside every run and recommendation so operators can audit behavior without leaving the platform. This document describes the key payloads the internal pipeline emits and stores.

## Structured pipeline payloads

The app-native pipeline emits a structured JSON object for each ticker it scores. This object is persisted as `analysis_json` for transparency.

- `analysis_json`: The canonical structured payload created during scoring. It now groups the diagnostics into a handful of logical sections so reviewers can find the key narrative, news, and signal data without scanning dozens of root-level fields:
  - `metadata`: timestamps, version, and the ticker that the pipeline just scored.
  - `trade`: direction confidence plus the derived entry, stop-loss, and take-profit values that form the actionable decision.
  - `summary`: the digest or LLM narrative text (`text`), how it was generated (`method`/`backend`/`model`), runtime metadata, the fallback digest, and any `error`/`llm_error` details.
  - `news`: the unified `items` array (title, summary, publisher, link, published_at, compound score, etc.), feed usage (`feeds_used`/`feed_errors`), item counts, and the keyword sentiment diagnostics (base `score`, `volatility`, `polarity_trend`, and `sources`).
  - `sentiment`: the final score/label stored in the feature vector plus the `enhanced` block that fuses summary tone, keyword sentiment, and technical context.
  - `context_flags`: the boolean keyword tags (`earnings`, `geopolitical`, `industry`, `general`) that the sentiment analyzer emits.
  - `feature_vectors`: nested `raw` and `normalized` payloads so auditors can inspect inputs before and after scaling.
  - `aggregations`, `confidence_weights`, and `aggregation_weights`: the weighted breakdowns and weight maps used to compute direction and confidence.
  - `diagnostics`: problems, news feed failures, and summary/LLM errors for quick troubleshooting.
By narrowing the number of top-level keys and keeping only the article array as the core list, every headline, digest, and diagnostic score remains discoverable while the payload stays readable for tooling and operator inspection.
- `raw_output`: Any scripted stdout/stderr emitted during scoring. Use this when `analysis_json` is missing fields or when data retrieval fails.
- `feature_vector_json`: Raw technical feature values collected before normalization (moving averages, RSI, ATR, momentum, etc.).
- `normalized_feature_vector_json`: The same features scaled to the ranges expected by the scoring weights. These normalized values are what the weights multiply to generate contributions.
- `aggregations_json`: Intermediate aggregate metrics such as `momentum_score`, `volatility_score`, and `trend_score`. These values help explain why a direction or confidence score was selected.
- `confidence_weights_json`: The per-feature weights loaded from `weights.json` and applied to the normalized vector to compute confidence contributions.
- `summary_method`: Describes how the summarization backend generated the summary (e.g., cache hit, `pi_agent`, `openai_api`, or `failed`).

## Recommendation-specific fields

Recommendations stored on each run mirror the data required for execution:

- `direction`: `LONG`, `SHORT`, or `NEUTRAL`, derived from comparing the bullish and bearish aggregated signals.
- `confidence`: A floating-point score in [0, 1] capturing the certainty of the direction.
- `entry_price`: Typically the latest close or a direction-adjusted value.
- `stop_loss` / `take_profit`: Levels derived from volatility-adjusted ATR/momentum context and the configured reward/risk multipliers.
- `indicator_summary`: A short, human-friendly description of the primary driving signals (reuse of the summarizer output).

## Diagnostics and timing

These fields appear on `RunDiagnostics` and help populate debugger/health views:

- `warnings`: Non-fatal issues encountered during scoring (missing data, fallback summaries, etc.).
- `provider_errors`: Failures reported by external providers (e.g., `yfinance` or summarization backends).
- `problems`: Any non-recoverable errors that aborted execution for a ticker.
- `news_feed_errors`: Provider issues specifically related to news retrieval.
- `summary_error` / `llm_error`: Errors emanating from the summary generation stage.
- `timing_json`: A breakdown of how long each phase took (data fetch, feature calc, scoring, persistence). Useful for spotting slow runs.
- `analysis_timestamp`: UTC timestamp when the pipeline produced the structured payload.

## Operational notes

- **Weights**: `weights.json` lives in `src/trade_proposer_app/data/`. The file is version-controlled and used for every scoring run. `AppPreflightService` verifies its presence during startup.
- **Preflight**: `/api/health/preflight` reports on the availability of `pandas`, `yfinance`, and the weights file to ensure the internal pipeline is runnable.
- **Summarization**: Operators configure the summary backend via `/settings` (news_digest for digest-only output, openai_api for OpenAI narratives, pi_agent for a local Pi CLI narrative). The form exposes Pi-specific fields (command, working directory, optional flags) so the pipeline can treat a vanilla Pi tool like any other LLM provider. Each run records the digest text plus the LLM metadata (backend, model, runtime, errors) and the derived `enhanced_sentiment` block inside `analysis_json`, so operators can compare the keyword-only and fused sentiment signals in the recommendation detail view.
- **Diagnostics reuse**: The same fields support the debugger, run detail pages, ticker pages, and `/api/health` so operators never lose sight of why a run succeeded or failed.
