# Target Architecture

## Overview

The redesigned app should be organized into four layers:

1. **Context**
2. **Exposure**
3. **Ticker setup**
4. **Trade plan**

The goal is to move away from a generic sentiment dashboard and toward a **short-horizon recommendation engine**.

## Layer 1: Context

This layer identifies what matters now.

It includes:

- macro context
- industry context

### Macro context
Macro should be a saliency engine.

Its job is to identify:

- major market-moving developments
- regime context
- regional exposure
- persistence vs escalation vs fading
- likely implications over the next few days

Examples:

- Iran conflict escalation
- oil upside pressure
- ECB restrictive stance
- European growth pressure
- risk-off regime

Macro should answer:

- what matters now?
- why does it matter?
- which markets and regions are exposed?
- is this development new, intensifying, or fading?

### Industry context
Industry context should not be only macro-derived.

It should combine:

1. macro-linked drivers
2. industry-native developments
3. read-throughs from important tickers in the industry

Industry-native developments include:

- innovations
- product cycles
- conferences
- pricing trends
- demand changes
- supply chain developments
- sector-specific regulation
- launches and partnerships

Industry should answer:

- what is happening in this industry right now?
- what macro forces are affecting it?
- what sector-specific developments matter independently of macro?
- what is the likely short-term directional pressure?

## Layer 2: Exposure

This layer maps context into impact.

It answers:

- which industries are exposed to active macro themes?
- which tickers are exposed to industry and macro themes?
- what is the likely direction of pressure?

This layer should explicitly model transmission channels instead of assuming that context automatically implies a ticker recommendation.

## Layer 3: Ticker setup

This layer estimates whether a specific ticker has a realistic short-horizon swing setup.

It should combine:

- macro context
- industry context
- ticker-specific catalysts
- ticker-specific sentiment
- technical setup
- volatility and timing
- liquidity and tradability

Suggested components:

- `macro_exposure_score`
- `industry_alignment_score`
- `ticker_catalyst_score`
- `ticker_sentiment_score`
- `technical_setup_score`
- `expected_move_score`
- `timing_score`
- `liquidity_score`
- `execution_quality_score`

Outputs should include:

- expected direction
- swing probability
- confidence
- tradeability status
- summary
- warnings

## Layer 4: Trade plan

This layer converts a valid ticker setup into a practical recommendation.

It should output:

- entry zone
- take profit
- stop loss
- horizon
- confidence
- risk/reward
- status

### Entry
Entry should come from market structure, not free-form summarization.

Possible approaches:

- breakout above resistance
- pullback into support or retest zone
- reclaim level after a catalyst

### Stop loss
Stop loss should come from invalidation logic plus volatility buffer.

Possible approaches:

- below swing low
- below breakout level minus ATR buffer
- above swing high for shorts

### Take profit
Take profit should come from expected move and structure.

Possible approaches:

- next resistance/support
- ATR multiple
- minimum acceptable risk/reward threshold

If a clean entry/stop/target cannot be derived, the recommendation should be downgraded to `watchlist` or `no_action`.

## Pipeline stages

### Stage A: Ingestion
Inputs:

- financial news
- macro reporting
- industry publications
- official releases
- ticker/company news
- curated social posts

Social is secondary for macro and industry.

### Stage B: Event extraction
This stage normalizes source items into reusable events/themes.

Examples:

- `geopolitics_middle_east_escalation`
- `oil_supply_shock_risk`
- `ecb_restrictive_bias`
- `airline_cost_pressure_from_oil`
- `semiconductor_ai_conference_tailwind`

This stage is important because it separates **saliency** from **sentiment polarity**.

### Stage C: Context synthesis
This stage creates:

- macro context objects
- industry context objects

### Stage D: Ticker setup evaluation
This stage scores near-term swing potential using context, catalysts, sentiment, and market structure.

### Stage E: Trade construction
This stage builds the final recommendation with entry, stop, target, and warnings.

## Summary generation rules

### Macro summaries
Macro summaries should focus on:

- top salient events
- confirmed developments
- what changed
- which regions and markets are exposed

### Industry summaries
Industry summaries should focus on:

- industry-native developments
- macro spillovers
- likely short-term directional implications

### Ticker summaries
Ticker summaries should focus on:

- catalyst
- exposure
- technical setup
- why the trade may work over the next few days
