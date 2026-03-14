# Raw Details Reference

This document explains every field currently shown or persisted as part of the app's raw recommendation and run details.

It also records a critical review of which fields are canonical, which are derived, and which are duplicated for compatibility with the upstream prototype.

## Why raw details exist

The main recommendation cards and run summaries are intentionally compact.

The raw details exist for the cases where you need to answer questions such as:
- Was this recommendation delayed in the queue, or slow because of analysis work?
- Did the prototype produce the expected structured payload?
- Did a warning come from missing data, summary generation, or the prototype process itself?
- Which inputs and weights shaped the recommendation?
- Is a surprising recommendation caused by sentiment, trend, or volatility features?

## Critical review summary

### Canonical fields kept by the app

These fields are the canonical raw details the app relies on today:
- run timestamps: `started_at`, `completed_at`
- run duration: `duration_seconds`
- run timing breakdown: `timing_json`
- recommendation structured payload: `analysis_json`
- recommendation process transcript: `raw_output`
- normalized diagnostics: `problems`, `news_feed_errors`, `summary_error`, `llm_error`

### Duplicated fields identified during review

The upstream prototype's `analysis_json` includes some duplicated fields.
They are still preserved in stored raw payloads because they can help with backward compatibility, troubleshooting, and future model analysis.

Important duplicates:
- `short_bullish`, `short_bearish`, `medium_bullish`, `medium_bearish`
  - also appear inside `feature_vector`
- `source_count`
  - can be derived from `sources`
- `direction`, `confidence`, `entry_price`, `stop_loss`, `take_profit`
  - also appear in the app's normalized recommendation record

These are still useful enough to keep in stored raw payloads, but they should not be treated as the only canonical source because the app already normalizes the same data separately.

Current app behavior after this review:
- stored `analysis_json` is preserved exactly as emitted by the prototype
- the raw-details viewer normalizes the displayed analysis payload by hiding the duplicated top-level short/medium tally fields when the same values are already present in `feature_vector`

### Fields intentionally kept even if they look close to duplicates

These pairs are similar but not actually interchangeable:
- `duration_seconds` vs `timing_json.total_execution_seconds`
  - `duration_seconds` is based on persisted run timestamps
  - `total_execution_seconds` is measured from in-process execution timing and can differ slightly
- `warnings` vs structured diagnostic fields
  - `warnings` is a user-facing merged summary
  - structured fields preserve cause-specific detail
- `analysis_json` vs `raw_output`
  - `analysis_json` is the structured prototype payload
  - `raw_output` is the full process transcript and is useful when parsing breaks or the prototype format changes

## Run-level raw details

Run-level raw details are attached to the run record itself.

### `started_at`
- Type: ISO datetime
- Meaning: when the worker actually claimed the queued run and started processing it
- Why it matters:
  - helps separate queue delay from actual analysis time
  - helps explain morning backlog or worker contention

### `completed_at`
- Type: ISO datetime
- Meaning: when the run reached a terminal state such as `completed`, `completed_with_warnings`, or `failed`
- Why it matters:
  - helps correlate app activity with logs, provider outages, or user actions
  - defines the end of persisted wall-clock run duration

### `duration_seconds`
- Type: float
- Meaning: wall-clock duration from `started_at` to `completed_at`
- Why it matters:
  - best top-level measure of how long the operator waited for a run result
  - useful for spotting regressions in the overall execution path
- Caveat:
  - not identical to `timing_json.total_execution_seconds`

### `timing_json`
- Type: JSON object stored as a string
- Meaning: internal timing breakdown for the run
- Why it matters:
  - shows where time was spent
  - helps separate slow queueing, slow ticker resolution, slow prototype execution, and slow persistence

#### `timing_json.queue_wait_seconds`
- Type: float
- Meaning: time between run creation and the worker claiming it
- Relevance:
  - high values suggest worker backlog, scheduler bursts, or too few workers

#### `timing_json.resolve_tickers_seconds`
- Type: float
- Meaning: time spent resolving the job's effective ticker list
- Relevance:
  - usually very small
  - unexpected growth suggests repository or DB lookup issues rather than analysis issues

#### `timing_json.recommendation_generation_seconds`
- Type: float
- Meaning: total time spent generating recommendations from the prototype for all tickers in the run
- Relevance:
  - primary signal for prototype slowness
  - large values can come from external feed delays, slow summarization, or heavy technical analysis work

#### `timing_json.persistence_seconds`
- Type: float
- Meaning: time spent saving generated recommendations to the database
- Relevance:
  - useful for detecting DB slowness separately from analysis slowness

#### `timing_json.finalize_seconds`
- Type: float
- Meaning: time spent marking the run complete or failed and persisting final timing data
- Relevance:
  - usually tiny
  - if it grows, the issue is likely repository/DB work, not market analysis

#### `timing_json.total_execution_seconds`
- Type: float
- Meaning: end-to-end measured execution time inside the worker orchestration path
- Relevance:
  - best internal benchmark for the worker path
  - useful when comparing runtime behavior between environments
- Caveat:
  - may differ slightly from `duration_seconds`

#### `timing_json.ticker_generation`
- Type: array of per-ticker objects
- Meaning: per-ticker breakdown for prototype generation time
- Relevance:
  - useful when a job covers multiple tickers and only one symbol is slow
  - helps distinguish a broad service slowdown from a ticker-specific issue

##### `timing_json.ticker_generation[].ticker`
- Type: string
- Meaning: ticker symbol that was processed
- Relevance:
  - identifies which ticker consumed time or failed before later tickers could run

##### `timing_json.ticker_generation[].duration_seconds`
- Type: float
- Meaning: time spent generating that ticker's recommendation
- Relevance:
  - allows direct comparison across tickers in the same run

## Recommendation-level raw details

Recommendation raw details live under the recommendation diagnostics.

### `analysis_json`
- Type: JSON object stored as a string
- Meaning: structured analysis payload produced by the upstream prototype script
- Why it matters:
  - richest structured explanation of why a recommendation was produced
  - useful for post-hoc analysis, debugging, and future model tuning

### `raw_output`
- Type: string
- Meaning: full combined stdout and stderr from the prototype subprocess
- Why it matters:
  - fallback source when parsing the structured payload fails
  - useful when the prototype output format changes or emits extra warnings

## Normalized diagnostics fields derived from `analysis_json`

These are extracted by the app and surfaced as structured diagnostics.
They are not the only raw details, but they are the fastest route to understanding a degraded result.

### `problems`
- Type: array of strings
- Meaning: normalized list of general issues reported by the prototype
- Relevance:
  - broad catch-all for degraded but still completed recommendations

### `news_feed_errors`
- Type: array of strings
- Meaning: feed-specific retrieval failures reported by the prototype
- Relevance:
  - directly answers whether missing or degraded news data affected the recommendation

### `summary_error`
- Type: string or null
- Meaning: error produced by the summarization path
- Relevance:
  - important when the recommendation still exists but the summary-based sentiment context degraded

### `llm_error`
- Type: string or null
- Meaning: model-related failure surfaced by the prototype summary stage
- Relevance:
  - helps distinguish LLM failures from general feed or parsing failures

## Full `analysis_json` field reference

The following fields are produced by the integrated prototype today.

### Top-level identity and recommendation fields

#### `analysis_timestamp`
- Type: ISO datetime string
- Meaning: when the prototype built the structured payload
- Relevance:
  - useful for correlating the prototype's own timing with run timestamps

#### `analysis_version`
- Type: string
- Meaning: upstream payload version identifier
- Relevance:
  - important when comparing runs across prototype revisions

#### `ticker`
- Type: string
- Meaning: analyzed ticker symbol
- Relevance:
  - sanity-checks that the payload matches the recommendation record

#### `direction`
- Type: string (`LONG` or `SHORT` in the current prototype)
- Meaning: prototype's chosen direction
- Relevance:
  - core trade thesis
- Critical review:
  - duplicated in the normalized recommendation row, but still useful to keep in the raw payload for integrity checks

#### `confidence`
- Type: float
- Meaning: confidence score produced by the prototype confidence model
- Relevance:
  - main confidence input shown in the app UI
- Critical review:
  - duplicated in the normalized recommendation row, but still useful for integrity checks

#### `entry_price`
- Type: float
- Meaning: proposed entry price used by the prototype
- Relevance:
  - lets you verify that persisted recommendation numbers match the raw payload

#### `stop_loss`
- Type: float
- Meaning: stop-loss level proposed by the prototype
- Relevance:
  - useful in risk-plan validation and troubleshooting

#### `take_profit`
- Type: float
- Meaning: take-profit level proposed by the prototype
- Relevance:
  - useful in risk-plan validation and troubleshooting

### Sentiment and summary context

#### `sentiment_score`
- Type: float
- Meaning: aggregate market/news sentiment score from the prototype
- Relevance:
  - one of the strongest inputs affecting confidence and direction

#### `sentiment_label`
- Type: string
- Meaning: coarse sentiment class such as bullish, bearish, or neutral
- Relevance:
  - useful human-readable summary of `sentiment_score`

#### `sources`
- Type: array of strings
- Meaning: source URLs or identifiers used in sentiment analysis
- Relevance:
  - shows what evidence the sentiment stage actually used

#### `source_count`
- Type: integer
- Meaning: number of sentiment sources the prototype counted
- Relevance:
  - quick data sufficiency signal
- Critical review:
  - technically derivable from `sources`, but kept because it is fast to inspect and useful if upstream source lists change shape in the future

#### `news_feeds_used`
- Type: array of strings
- Meaning: named feed integrations that successfully produced input
- Relevance:
  - shows which external services contributed to the run

#### `news_feed_errors`
- Type: array of strings
- Meaning: named feed integrations that failed or were unavailable
- Relevance:
  - critical for deciding whether a recommendation is degraded but still usable

#### `env_overrides`
- Type: object
- Meaning: environment overrides seen by the prototype when gathering feeds
- Relevance:
  - mainly useful in troubleshooting non-standard local setups
  - low day-to-day importance, but valuable for future support/debugging

#### `resource_hosts`
- Type: array of strings
- Meaning: normalized hostnames of some source URLs
- Relevance:
  - quick overview of which domains contributed to sentiment

#### `event_contexts`
- Type: array of strings
- Meaning: event/context labels inferred by the sentiment pipeline
- Relevance:
  - helps explain why sentiment was classified a certain way

#### `summary`
- Type: string
- Meaning: generated news summary text
- Relevance:
  - concise human-readable explanation of the news context behind the recommendation

#### `summary_method`
- Type: string
- Meaning: summarization path used by the prototype, such as a successful method name or `failed`
- Relevance:
  - tells you whether the summary came from the expected backend

#### `summary_error`
- Type: string or null
- Meaning: summarization failure reported by the prototype
- Relevance:
  - key signal for deciding whether degraded news context should lower trust in the recommendation

#### `problems`
- Type: array of strings
- Meaning: accumulated issues from feed gathering, sentiment processing, or summarization
- Relevance:
  - broad top-level explanation of degradation

### Feature and model explanation fields

#### `feature_vector`
- Type: object
- Meaning: raw feature values used by the prototype before normalization
- Relevance:
  - most useful section when you want to understand why the recommendation moved in a particular direction

#### `normalized_feature_vector`
- Type: object
- Meaning: normalized feature values scaled into the prototype's comparison range
- Relevance:
  - useful when reasoning about weights and relative feature importance

#### `aggregations`
- Type: object
- Meaning: combined internal outputs derived from normalized features and aggregation weights
- Relevance:
  - best high-level explanation of how the prototype combined raw inputs into directional, risk, and entry signals

#### `confidence_weights`
- Type: object
- Meaning: weights used to compute the confidence score
- Relevance:
  - important for future weight tuning and regression analysis

#### `aggregation_weights`
- Type: object
- Meaning: weights used to combine normalized features into direction, risk, and entry aggregations
- Relevance:
  - useful for debugging the model configuration and future tuning work

### Short/medium technical tally fields

#### `short_bullish`
#### `short_bearish`
#### `medium_bullish`
#### `medium_bearish`
- Type: numeric counts
- Meaning: simple short- and medium-horizon bullish/bearish tallies used by the prototype
- Relevance:
  - quick sanity checks of trend construction
- Critical review:
  - duplicated in `feature_vector`
  - preserved for compatibility and quick inspection, but not treated as separate canonical fields

### Additional aggregate statistics

#### `news_point_count`
- Type: integer or float in the current payload
- Meaning: number of sentiment news points considered by the prototype
- Relevance:
  - data sufficiency signal for sentiment stability

#### `polarity_trend`
- Type: float
- Meaning: directional balance of positive vs negative sentiment points
- Relevance:
  - helps explain whether a neutral average score still hides a directional skew

#### `sentiment_volatility`
- Type: float
- Meaning: variability of sentiment point values
- Relevance:
  - high volatility can indicate unstable or conflicting news flow

## `feature_vector` field reference

The prototype currently emits the following raw feature values:
- `price_close`: latest close price
- `sma20`: 20-day simple moving average
- `sma50`: 50-day simple moving average
- `sma200`: 200-day simple moving average
- `rsi`: 14-day RSI
- `atr`: 14-day ATR
- `atr_pct`: ATR as a percentage of price
- `normalized_atr_pct`: normalized ATR percentage reused downstream
- `volatility_band_upper`: prototype upper volatility band
- `volatility_band_lower`: prototype lower volatility band
- `volatility_band_width`: distance between upper and lower volatility bands
- `momentum_short`: short-horizon momentum
- `momentum_medium`: medium-horizon momentum
- `momentum_long`: long-horizon momentum
- `price_change_1d`: 1-day price change
- `price_change_10d`: 10-day price change
- `price_change_63d`: 63-day price change
- `price_change_126d`: 126-day price change
- `entry_delta_2w`: 2-week entry delta
- `entry_delta_3m`: 3-month entry delta
- `entry_delta_12m`: 12-month entry delta
- `price_vs_sma20_ratio`: price relative to SMA20
- `price_vs_sma50_ratio`: price relative to SMA50
- `price_vs_sma200_ratio`: price relative to SMA200
- `price_vs_sma20_slope`: slope of the price-vs-SMA20 relationship
- `price_vs_sma50_slope`: slope of the price-vs-SMA50 relationship
- `price_vs_sma200_slope`: slope of the price-vs-SMA200 relationship
- `short_bullish`: short bullish tally
- `short_bearish`: short bearish tally
- `medium_bullish`: medium bullish tally
- `medium_bearish`: medium bearish tally
- `sentiment_score`: aggregate sentiment score reused as a feature
- `source_count`: number of sources reused as a feature
- `context_count`: number of detected contexts
- `news_point_count`: number of sentiment news points reused as a feature
- `polarity_trend`: positive vs negative sentiment balance
- `sentiment_volatility`: dispersion of sentiment points
- `context_tag_earnings`: whether earnings context was present
- `context_tag_geopolitical`: whether geopolitical context was present
- `context_tag_industry`: whether industry/regulatory context was present
- `context_tag_general`: whether generic market context was present

Relevance:
- this is the best section for detailed post-mortem analysis of why the model leaned a certain way
- these fields are raw rather than normalized, so they are easiest to compare to outside market data

## `normalized_feature_vector` field reference

`normalized_feature_vector` contains the same feature keys as `feature_vector`, but scaled into the prototype's normalized range.

Relevance:
- useful when reading the weight-based sections
- especially helpful when explaining why a large raw value did or did not matter after normalization

## `aggregations` field reference

### `direction_score`
- Meaning: normalized directional strength after combining trend and sentiment inputs
- Relevance:
  - strongest compact explanation of directional bias

### `risk_offset_pct`
- Meaning: normalized risk adjustment percentage
- Relevance:
  - explains how volatility and sentiment instability changed the stop/target posture

### `risk_stop_offset`
- Meaning: ATR-based stop offset implied by the risk aggregation
- Relevance:
  - useful in diagnosing unexpectedly wide or tight stops

### `risk_take_profit_offset`
- Meaning: ATR-based take-profit offset implied by the risk aggregation
- Relevance:
  - useful in diagnosing unexpectedly conservative or aggressive targets

### `entry_adjustment`
- Meaning: internally adjusted entry estimate
- Relevance:
  - helps explain how trend and volatility influenced entry bias

### `entry_drift_signal`
- Meaning: signed entry drift signal used by the prototype
- Relevance:
  - useful when the recommended entry appears slightly off the current price

## `confidence_weights` field reference

The prototype currently uses keys such as:
- `base`
- `sentiment`
- `price_above_sma50`
- `price_above_sma200`
- `rsi_penalty`
- `atr_penalty`

Relevance:
- these weights explain how much each confidence component contributed to the final confidence value

## `aggregation_weights` field reference

### `aggregation_weights.direction`
Current keys:
- `short_momentum`
- `medium_momentum`
- `long_momentum`
- `sentiment_bias`
- `base`

### `aggregation_weights.risk`
Current keys:
- `atr`
- `momentum`
- `sentiment_volatility`
- `base`

### `aggregation_weights.entry`
Current keys:
- `short_trend`
- `medium_trend`
- `long_trend`
- `volatility`
- `base`

Relevance:
- these sections are most useful for model tuning, regression analysis, and future explainability work

## How to interpret raw details efficiently

Recommended order of inspection:
1. Check run status, `error_message`, and `duration_seconds`
2. Check `timing_json` to see whether the problem was queueing, execution, or persistence
3. Check normalized diagnostics: `problems`, `news_feed_errors`, `summary_error`, `llm_error`
4. Check `summary`, `sentiment_score`, and `event_contexts`
5. Check `aggregations`
6. Only then open the full `feature_vector`, `normalized_feature_vector`, and `raw_output`

This keeps investigation fast while preserving the richer payload for future debugging and model analysis.
