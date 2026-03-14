# Recommendation Methodology

This document explains how the current recommendation engine composes gathered data into a trade recommendation.

It reflects the current implementation in:
- `/home/aurelio/workspace/pi-mono/.pi/skills/trade-proposer/scripts/propose_trade.py`

It should be updated whenever the recommendation logic, feature set, or weighting model changes.

## Scope

The current recommendation engine is still the integrated prototype strategy. The app shells out to the prototype and stores the resulting recommendation, while keeping diagnostics and raw analysis payloads available as separate execution context tied back to the source run.

This document describes:
- what data is gathered
- what indicators are computed from that data
- how those indicators contribute to intermediate values
- how those intermediate values contribute to the final recommendation
- known weaknesses in the current strategy

## High-level flow

For each ticker:

1. Gather news and social inputs from multiple feeds.
2. Run sentiment analysis on the aggregated text.
3. Generate a short LLM-based news summary.
4. Download one year of market price history.
5. Compute technical indicators and derived features.
6. Normalize features.
7. Compute intermediate aggregation values.
8. Determine direction, confidence, entry, stop loss, and take profit.
9. Persist a recommendation object containing the trade-ready fields plus compact indicator context.
10. Keep richer diagnostics and raw analysis payloads available for run/debug investigation.

## External data gathered

### News and social feeds

The prototype attempts to gather data from these sources:
- Yahoo Finance
- NewsAPI
- Alpha Vantage
- Finnhub
- Alpaca News
- Nitter Tweets

The exact set used for a run depends on:
- whether the source script exists
- whether the required API keys are available
- whether the call succeeds before timeout

### Market history

The prototype fetches one year of price history from `yfinance` for the ticker.

### Runtime configuration

The prototype also loads:
- environment overrides from `env_overrides.json` when present
- weight configuration from `weights.json`

## What data produces what indicator

## 1. Sentiment indicators

The sentiment pipeline produces:
- `sentiment_score`
- `sentiment_label`
- `sources`
- `event_contexts`
- `news_points`
- `news_point_count`
- `feeds_used`
- `feed_errors`

### 1.1 `sentiment_score`

Produced by:
- the market sentiment analyzer over aggregated news/social text

Used in:
- final `confidence`
- `feature_vector.sentiment_score`
- `aggregations.direction_score`

### 1.2 `sentiment_label`

Produced by:
- the same sentiment analyzer

Used in:
- human-readable output only
- does not directly change the numeric recommendation once `sentiment_score` is already computed

### 1.3 `sources`

Produced by:
- sentiment analyzer parsing source links from the aggregated feed content

Used to compute:
- `source_count = len(sources)`
- `resource_hosts` for reporting

### 1.4 `event_contexts`

Produced by:
- sentiment analyzer context tagging

Mapped into binary context flags:
- `context_tag_earnings`
- `context_tag_geopolitical`
- `context_tag_industry`
- `context_tag_general`

Used in:
- `feature_vector`
- normalization and raw analysis payload

Current implementation note:
- these context flags are recorded, normalized, and persisted
- they are not currently used directly by the `direction`, `risk`, or `entry` aggregation formulas

### 1.5 `news_points`

Produced by:
- sentiment analyzer extraction of per-item sentiment points

Used to compute:
- `polarity_trend`
- `sentiment_volatility`

#### `polarity_trend`
- computed as `(positive - negative) / total`
- a point is positive if compound sentiment > `0.05`
- a point is negative if compound sentiment < `-0.05`

#### `sentiment_volatility`
- computed as population standard deviation of compound sentiment values

Used in:
- `feature_vector`
- `aggregations.risk_offset_pct`

### 1.6 LLM summary

Produced by:
- the news summarizer skill

Used in:
- `analysis.summary`
- operator interpretation and diagnostics

Current implementation note:
- the summary does not currently feed directly into the numeric recommendation formula
- it is explanatory output, not a direct scoring input

## 2. Technical indicators

These are computed from one year of historical OHLC data.

### 2.1 Moving averages

Produced indicators:
- `SMA_20`
- `SMA_50`
- `SMA_200`

Used to derive:
- `price_above_sma50`
- `price_above_sma200`
- `trend_bullish`
- `price_vs_sma20_ratio`
- `price_vs_sma50_ratio`
- `price_vs_sma200_ratio`
- `price_vs_sma20_slope`
- `price_vs_sma50_slope`
- `price_vs_sma200_slope`

### 2.2 RSI

Produced indicator:
- `RSI_14`

Used in:
- short-term bullish/bearish tally
- final `confidence`
- `feature_vector.rsi`

### 2.3 ATR

Produced indicator:
- `ATR_14`

Used in:
- `atr_pct`
- baseline stop loss and take profit distances
- `aggregations.risk_offset_pct`
- `aggregations.entry_adjustment`

### 2.4 Price momentum and returns

Produced indicators:
- `momentum_short` = 5-day percent change
- `momentum_medium` = 21-day percent change
- `momentum_long` = 63-day percent change
- `price_change_1d`
- `price_change_10d`
- `price_change_63d`
- `price_change_126d`
- `entry_delta_2w`
- `entry_delta_3m`
- `entry_delta_12m`

Used in:
- `feature_vector`
- direction aggregation
- risk aggregation
- entry aggregation

### 2.5 Volatility band features

Produced indicators:
- `volatility_band_upper = SMA_20 + ATR_14`
- `volatility_band_lower = SMA_20 - ATR_14`
- `volatility_band_width = upper - lower`

Used in:
- `feature_vector`
- entry aggregation

## 3. Rule-based directional tallies

The prototype creates simple bullish/bearish counts.

### 3.1 Short-term tally

Bullish points:
- price > SMA 20
- RSI < 30
- price above SMA 50

Bearish points:
- price <= SMA 20
- RSI > 70
- price not above SMA 50

Stored as:
- `short_bullish`
- `short_bearish`

### 3.2 Medium-term tally

Bullish points:
- price > SMA 50
- price > SMA 200
- price_above_sma200

Bearish points:
- inverse of the above

Stored as:
- `medium_bullish`
- `medium_bearish`

Current implementation note:
- these tallies are stored in the feature vector and raw payload
- they are not directly used in the final direction aggregation formula
- this creates some redundancy between displayed fields and the actual scoring model

## 4. Direction decision

The current direction decision is not derived from the weighted aggregation score.

It is determined by a single rule:
- if `price > SMA_200`, direction = `LONG`
- otherwise, direction = `SHORT`

This means:
- long-term trend dominates the direction choice
- sentiment and shorter-horizon momentum do not directly flip direction
- the weighted `direction_score` is explanatory only in the current implementation

This is a major design constraint and also a weakness.

## 5. Confidence calculation

The prototype computes confidence with a linear weighted formula:

`confidence = clamp(base + sentiment_term + sma50_term + sma200_term + rsi_term + atr_term, 0, 95)`

The exact numeric weights come from:
- `.pi/skills/trade-proposer/data/weights.json`
- specifically the `confidence` section

### Inputs used

For `LONG`:
- `sent_f = sentiment_score`
- `sma50_f = price_above_sma50`
- `sma200_f = price_above_sma200`
- `rsi_f = RSI_14`

For `SHORT`:
- `sent_f = -sentiment_score`
- `sma50_f = 1 - price_above_sma50`
- `sma200_f = 1 - price_above_sma200`
- `rsi_f = 100 - RSI_14`

For both:
- `atr_pct`

### Weight keys

The confidence formula uses these weight keys:
- `base`
- `sentiment`
- `price_above_sma50`
- `price_above_sma200`
- `rsi_penalty`
- `atr_penalty`

### Interpretation

- higher aligned sentiment increases confidence
- price being above key moving averages helps a `LONG` and hurts a `SHORT`
- price being below key moving averages helps a `SHORT` and hurts a `LONG`
- RSI is treated directionally
- ATR percent affects confidence through its own penalty weight

## 6. Feature normalization

The strategy normalizes many features to a `0..1` range.

### Range source

Normalization bounds come from:
- min/max ranges observed in the current one-year history window for market-history-derived columns
- fixed manual ranges for sentiment/context/count features

### Important implication

Because normalization uses the current ticker's one-year history window:
- normalized values are relative to that ticker's recent history
- normalized values are not directly comparable across different tickers without caution

## 7. Weighted aggregation values

The strategy computes weighted aggregation outputs for:
- direction
- risk
- entry

The exact numeric weights come from:
- `.pi/skills/trade-proposer/data/weights.json`
- specifically the `aggregators` section

## 7.1 Direction aggregation

Formula shape:

`direction_signal = base`
`+ centered(momentum_short) * short_momentum`
`+ centered(momentum_medium) * medium_momentum`
`+ centered(momentum_long) * long_momentum`
`+ centered(sentiment_score) * sentiment_bias`

`direction_score = clamp(0.5 + direction_signal, 0, 1)`

Where:
- `centered(x) = x - 0.5`

Weight keys:
- `base`
- `short_momentum`
- `medium_momentum`
- `long_momentum`
- `sentiment_bias`

Current implementation note:
- `direction_score` is stored and shown in raw details
- it does not currently decide `LONG` vs `SHORT`

## 7.2 Risk aggregation

Formula shape:

`risk_signal = base`
`+ centered(atr_pct) * atr`
`+ centered(momentum_medium) * momentum`
`+ normalized(sentiment_volatility) * sentiment_volatility`

`risk_offset_pct = clamp(risk_signal, -1, 1)`
`risk_stop_offset = risk_offset_pct * ATR_14`
`risk_take_profit_offset = risk_offset_pct * ATR_14 * 2`

Weight keys:
- `base`
- `atr`
- `momentum`
- `sentiment_volatility`

Current implementation note:
- these values are computed and persisted
- they are currently explanatory only
- the final stop loss and take profit do not use these weighted offsets

## 7.3 Entry aggregation

Formula shape:

`entry_signal = base`
`+ centered(momentum_short) * short_trend`
`+ centered(momentum_medium) * medium_trend`
`+ centered(momentum_long) * long_trend`
`+ centered(volatility_band_width) * volatility`

`entry_adjustment = current_price + entry_signal * ATR_14`

Weight keys:
- `base`
- `short_trend`
- `medium_trend`
- `long_trend`
- `volatility`

Current implementation note:
- `entry_adjustment` is computed and persisted
- the final trade entry does not currently use it

## 8. Final trade plan values

### Direction

Determined by:
- `price > SMA_200`

### Entry price

Current final entry:
- `entry = current_price`

Weighted entry aggregation is not currently applied.

### Stop loss and take profit

For `LONG`:
- `stop_loss = entry - 1.5 * ATR_14`
- `take_profit = entry + 3.0 * ATR_14`

For `SHORT`:
- `stop_loss = entry + 1.5 * ATR_14`
- `take_profit = entry - 3.0 * ATR_14`

This is a fixed 1:2 ATR-based risk/reward rule.

## 9. What actually drives the final recommendation today

In practical terms, the current final recommendation is driven mainly by:

1. `price vs SMA_200`
   - decides direction
2. confidence weights from `weights.json`
   - adjust conviction level
3. `ATR_14`
   - determines stop loss and take profit distance
4. current price
   - determines market entry level

Many other features are computed, normalized, and persisted, but currently serve more as:
- diagnostic context
- future model-tuning material
- explainability support

rather than direct final decision drivers.

## 10. Weak points and limitations

## 10.1 Direction is overly dominated by one long-term trend rule

The direction is currently set only by `price > SMA_200`.

Weakness:
- strong short-term bearish news can still produce a `LONG` if price remains above the 200-day average
- strong positive catalysts can still produce a `SHORT` if price remains below the 200-day average

## 10.2 Weighted direction score is not used to choose direction

The system computes `direction_score` but does not use it to make the final directional decision.

Weakness:
- the strategy pays the complexity cost of a weighted model without fully using it in the final action
- raw details may suggest nuance that the final recommendation ignores

## 10.3 Weighted risk and entry outputs are not applied to the final plan

The system computes:
- `risk_offset_pct`
- `risk_stop_offset`
- `risk_take_profit_offset`
- `entry_adjustment`

But the final recommendation still uses:
- market entry at current price
- fixed ATR-based stop loss / take profit rules

Weakness:
- the richer calculations do not currently improve the executed plan

## 10.4 Sentiment quality depends on upstream feed coverage and extraction quality

Weakness:
- missing API keys, feed failures, or partial news coverage can distort `sentiment_score`
- tweet/news mixes may vary in quality and timeliness
- duplicates across sources may still bias sentiment if not handled upstream

## 10.5 LLM summary is not a direct scoring input

Weakness:
- the summary improves readability but not the numeric decision process
- a highly accurate summary does not directly improve the trade output today

## 10.6 Normalization is ticker-relative, not market-global

Weakness:
- the same normalized value can mean different real-world conditions across different tickers
- cross-ticker comparability is limited

## 10.7 Confidence is capped and partially heuristic

Weakness:
- the confidence formula is linear and heuristic rather than calibrated against realized outcomes
- confidence should not be interpreted as a statistically validated probability of success

## 11. How to inspect the live details for one run

Use the app UI to inspect:
- run detail raw details
- debugger raw details
- ticker raw prototype analysis payloads

The persisted `analysis_json` includes:
- gathered sources and feed errors
- sentiment outputs
- summary outputs
- feature vectors
- normalized feature vectors
- aggregation values
- confidence and weight snapshots

For field-by-field payload details, also see:
- `docs/raw-details-reference.md`

## 12. Recommended interpretation

This strategy should currently be interpreted as:
- a trend-following recommendation engine with sentiment-informed confidence
- ATR-based risk framing
- substantial diagnostic instrumentation for later refinement

It should not yet be interpreted as:
- a fully integrated multi-factor model where all computed features directly drive the final trade decision
- a calibrated probability model
- a robust execution strategy validated across all market regimes
