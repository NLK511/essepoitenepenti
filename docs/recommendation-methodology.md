# Recommendation Methodology

This document explains how the Trade Proposer App produces recommendations using its app-native scoring pipeline. The pipeline runs entirely inside this repository: it gathers OHLC price history through `yfinance`, enriches it with technical indicators via `pandas`, normalizes the resulting feature vectors, applies the stored weights in `src/trade_proposer_app/data/weights.json`, and emits direction, confidence, entry, stop-loss, and take-profit signals along with diagnostics.

## Pipeline overview

The internal pipeline is orchestrated by `ProposalService`. A run payload includes one or more tickers sourced from a job or watchlist. For every ticker, the pipeline:

1. pulls recent OHLC data (default: 1 year daily) with `yfinance`.
2. builds a feature matrix with standard indicators (momentum, volatility, trend, mean reversion, ATR, RSI, etc.).
3. normalizes each feature to the configured range and stores the raw/normalized vectors for traceability.
4. applies the stored weights to compute aggregated signal metrics, direction bias, and confidence.
5. translates the biased direction into entry, stop-loss, and take-profit levels informed by momentum/volatility context.
6. records diagnostics, the feature payloads, and the normalized recommendation plus summary text.

After the price-derived features are ready, the pipeline pulls in news via the internal `NewsIngestionService`, scores the resulting articles with a lightweight sentiment analyzer, and folds the sentiment signals back into the normalized feature vector before emitting the recommendation.

If any step fails (missing data, API error, or weight load issue), the run surfaces a failure with contextual warnings rather than falling back to unsafe defaults.

## Data sources and enrichment

- **Market data**: `yfinance` provides OHLC history and volume for the requested ticker. The pipeline caches per-ticker histories for the duration of a run and logs retrieval timing in the `timing_json` metadata.
- **News ingestion**: `ProposalService` now runs `NewsIngestionService` with the configured provider credentials (NewsAPI, Finnhub, etc.). It normalizes the returned articles, deduplicates links, and records which feeds succeeded or failed. A lightweight sentiment analyzer scores the collected content by weighting positive/negative keywords in the headline (1.7x boost) and body (1.2x) while sweeping a broader dictionary (for example, `guidance`, `exceed`, `resilient`, and `downturn`). A tighter smoothing constant (0.25) keeps the per-article `compound` values inside [-1.0, +1.0] even when a headline is strongly directional, yet lets even a single match nudge the aggregate `sentiment_score` away from strict neutrality while `coverage_insights` explains every remaining zero. That analyzer exports `context_tag_*` flags and contributes `sentiment_score`, `sentiment_volatility`, `polarity_trend`, and `news_point_count` to the feature vector. When no providers are configured the pipeline still produces a recommendation but logs the missing news feeds in `news_feed_errors` and falls back to the price-only summary text.

### News coverage {#news-coverage}

The news payload inside `analysis_json.news` carries aggregated totals (item_count, point_count, source_count) so downstream dashboards can surface how much coverage backed each recommendation. The news digest held in `analysis_json.news.digest` highlights the most relevant articles, while the individual `news.items` records the normalized `compound` scores and publisher metadata referenced by the run-detail structured diagnostics block.
- **Summaries**: The pipeline always builds a short headline digest (up to three articles) so `analysis_json.news.digest` always contains something meaningful even when the LLM path fails. Operators can optionally configure the `openai_api` backend (OpenAI) or the `pi_agent` backend (local Pi) so the same news digest plus a lightweight technical snapshot is sent to the in-app LLM summarizer. That LLM narrative is recorded in `analysis_json.summary` along with the `summary_backend`/`summary_model` metadata, runtime, and any LLM errors. When the LLM summary succeeds, its tone is fused with the keyword-based `sentiment_score` and the technical snapshot to produce `analysis_json.sentiment.enhanced` (score, label, and component contributions), which may replace the sentiment signal that the feature vector samples during scoring.

## Feature engineering

Feature vectors combine:

- **Trend indicators**: SMAs (20/50/200), momentum direction, crossovers.
- **Reversion signals**: Distance from long-term averages, mean-reversion momentum.
- **Volatility**: ATR, Bollinger-style bands, daily return dispersion.
- **Momentum**: RSI, MACD-like spread proxies, entry momentum relative to lookback windows.
- **Liquidity/volume**: Volume compared to its trailing average, plus volatility-weighted volume where available.

Each raw feature is stored in `feature_vector_json` and also normalized into the [-1, +1] or [0, 1] range depending on its type. The normalized vector is persisted in `normalized_feature_vector_json` so downstream audits can reconstruct how the scoring weights saw the inputs.

### Feature vectors {#feature-vectors}

The normalized vectors expose highlights such as `sentiment_score`, `enhanced_sentiment_score`, and `news_point_count`, which the structured diagnostics section renders beside confidence weights so operators can compare runs at a glance. The raw feature vector is preserved in `feature_vector_json` for deeper investigation.

## Scoring and weights

`weights.json` defines several layers of scoring:

- **Confidence weights** assign relative importance to each normalized feature. Multiplying the normalized vector by the confidence weights produces a per-feature contribution array (`confidence_weights_json`).
- **Direction bias** aggregates weighted features to determine whether the ticker is more bullish or bearish. The pipeline computes separate long and short aggregates and compares their magnitudes.
- **Aggregators** store intermediate sums such as `momentum_score`, `volatility_score`, and `trend_score`, which are persisted in `aggregations_json` for diagnostics.

### Aggregations {#aggregations}

The aggregator totals (`momentum_score`, `volatility_score`, `trend_score`, etc.) translate the per-feature contributions into macro drivers that the optimizer can review later. These totals are surfaced in the structured diagnostics panel to show which aspects of the feature vector dominated the directional bias.

### Confidence weights {#confidence-weights}

The confidence weights (`confidence_weights_json`) hold the multipliers applied to each normalized feature. Together with the normalized vector and aggregator totals, they help operators trace how much each signal moved the final confidence score.

The final confidence score is a function of the aggregated metrics, capped in [0, 1], with a small baseline added to avoid zero-footprint outputs. The output direction is `LONG` if the long bias exceeds the short bias by a threshold, `SHORT` if the reverse is true, otherwise `NEUTRAL`.

## Price levels and risk

Entry, stop-loss, and take-profit levels come from the same feature context and the aggregator weights in `weights.json`:

- **Entry** starts from the latest price but can shift by a small amount derived from the `entry` aggregator, which combines medium-term momentum, trend bias, and volatility so the price level steps in the direction the market is already moving.
- **Stop-loss** adds an ATR-based base distance and then applies the `risk` aggregator’s offset, which itself incorporates ATR, medium momentum, and sentiment volatility. That means stops quietly widen when momentum is strong or coverage is good, and they tighten when the sentiment signal is noisy.
- **Take-profit** begins from the stop distance, multiplies it by the reward/risk factor, and then adds the `risk` aggregator’s profit offset, so stronger signals push profit targets further from the entry while still respecting the core volatility budget.

These price levels are captured on each recommendation and stored in the persistent `Recommendation` record stored with the run.

### Proposal structure {#proposal-structure}

Each recommendation record stores the entry, stop-loss, and take-profit levels alongside the aggregated signal context so operators can see which aggregator/trend inputs pushed the price levels. The projection includes the bias (`LONG`, `SHORT`, `NEUTRAL`), the confidence score, and the digest that motivates the direction; the run detail page surfaces these fields with explicit labels so audit trails stay readable.

## Diagnostics and outputs {#diagnostics}

Each run stores:

- `analysis_json`: the structured payload describing the computed signals, aggregator breakdowns, and narrative summary (or headline digest) from the pipeline. It now exposes discrete sections (`metadata`, `trade`, `summary`, `news`, `sentiment`, `context_flags`, `feature_vectors`, `aggregations`, `confidence_weights`, `aggregation_weights`, and `diagnostics`), so the digest appears under `analysis_json.news.digest`, the LLM narrative under `analysis_json.summary.text`, and the fused sentiment under `analysis_json.sentiment.enhanced`. `analysis_json.news.items` still merges the latest articles with their sentiment scores for easy auditing, and the run detail view renders these sections directly so operators can explore them without parsing raw JSON.
- `raw_output`: stdout/stderr emitted during the pipeline, useful for debugging unexpected fetch failures.
- `feature_vector_json` and `normalized_feature_vector_json`: raw and normalized feature values.
- `aggregations_json`: intermediate aggregates, such as momentum/volatility subscores.
- `confidence_weights_json`: the weights applied to each feature in the confidence computation.
- `summary_method`: the summarization path taken (e.g., `news_digest` when a headline digest was assembled, `llm_summary` when the configured LLM produced the narrative, or `price_only` when no news articles were available). Diagnostics now collate the digest, metadata, and fused sentiment so downstream tools can reconstruct the reasoning from a single structured object.

### Structured diagnostics {#structured-diagnostics}

Structured diagnostics group the notable sections of `analysis_json` (feature vectors, aggregations, confidence weights, context flags, and news coverage) so operators can inspect the signals without parsing raw JSON. The run detail UI mirrors this layout and surfaces the same data in labeled blocks with section descriptions. Numeric fields such as normalized highlights, enhanced sentiment, and inline article scores now receive hue-based accent colors so operators can instantly spot positive, neutral, or negative readings without reading raw values.

### Context flags {#context-flags}

Context flags (anything under `analysis_json.context_flags`, including `news_provider_*` and `alert_mode`) act as triggers when the pipeline sees specific conditions—e.g., low liquidity, missing news coverage, or aggregated conflicts. The run detail view renders the positive flags so operators know why a recommendation gained or lost confidence.

### Raw output {#raw-output}

`raw_output` holds the stdout/stderr recorded during the pipeline run. Use it when the structured payload lacks enough detail; it still surfaces fetch errors, warnings, and other diagnostics emitted by subprocesses or external providers.

The diagnostics buckets (`warnings`, `provider_errors`, `problems`) accumulate context for UI surfaces like the debugger and run detail pages.

## Summary & sentiment {#summary-and-sentiment}

Every run builds a headline digest from the freshest news items (up to three titles) so the UI has something to render even when the external providers or LLM are unavailable. Operators can opt into the `openai_api` or `pi_agent` backend via `/settings`; when credentials or the `pi` CLI configuration (command, working directory, optional flags) are saved, the digest plus a concise technical snapshot (price, RSI, SMA deltas, ATR) is sent to the in-app LLM summarizer.

### Summary method {#summary-method}

The digest and provider metadata now live at `analysis_json.news.digest`, while the resulting narrative, backend info, runtime, and errors appear under `analysis_json.summary`. When the LLM summary succeeds, the pipeline merges its tone with the keyword-based sentiment and the technical context to produce `analysis_json.sentiment.enhanced`, and that fused score replaces the base sentiment signal in the feature vector so the scoring weights can lean on a richer understanding of the ticker context. The `summary_method` field records which path produced the narrative (`news_digest`, `llm_summary`, or `price_only`) so downstream operators can reproduce the behavior when auditing.

### Sentiment coverage {#sentiment-coverage}

`analysis_json.sentiment` now exposes `keyword_hits` and `coverage_insights` so every run documents why its sentiment score may stay at zero. `keyword_hits` counts how many positive or negative keywords were matched in the fetched articles, while `coverage_insights` lists explicit reasons (e.g., no articles fetched, no keyword matches, or provider errors) that explain a neutral output. Each coverage insight string mirrors the `NaiveSentimentAnalyzer` diagnostics (for example, `news: no articles fetched; providers may be missing or rate limited` or `news: articles arrived but no sentiment keywords matched`), so operators instantly know whether the neutrality signals missing data rather than a true market pause. The run detail page surfaces these insights inside the Sentiment coverage block before the structured diagnostics’ raw JSON view, giving operators quick context when coverage is sparse or missing entirely.

## App-native independence

Because the pipeline is self-contained, the app no longer depends on any external prototype repository. All inputs, weights, diagnostics, and the new news ingestion flow live inside this repository, and the worker can run the pipeline just by installing `pandas`, `yfinance`, and the other declared dependencies (plus configuring any desired news provider credentials). The NaiveSentiment analyzer now leans on a broader, highly resilient keyword set, and the signal integrity policy ensures that headline-light runs remain neutral when no keywords match instead of quietly defaulting to a synthesized score.

Scheduled weight optimization now shares that same footprint: it counts resolved recommendations from the app database, mutates the tracked `weights.json`, and stores a backup/rollback artifact so the job remains reproducible without touching the legacy scripts.
