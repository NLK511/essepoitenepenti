# Target Architecture

**Status:** active redesign reference

## Purpose

This doc describes the target shape of the redesign.

It splits the system into four layers:
1. **Context**
2. **Exposure**
3. **Ticker setup**
4. **Trade plan**

Near-term, this should be read as a shortlist, setup-evaluation, and trade-framing architecture, not as proof of general predictive skill.

## The four layers

### 1. Context
This layer identifies what matters now.

It includes:
- macro context
- industry context

#### Macro context
Macro should act as a saliency engine.

It should identify:
- major market-moving developments
- regime context
- regional exposure
- persistence vs escalation vs fading
- likely implications over the next few days

Macro should answer:
- what matters now?
- why does it matter?
- which markets and regions are exposed?
- is this development new, intensifying, or fading?

#### Industry context
Industry context should not be only macro-derived.

It should combine:
1. macro-linked drivers
2. industry-native developments
3. read-throughs from important tickers in the industry

Industry-native developments include product cycles, conferences, pricing trends, demand changes, supply-chain changes, sector-specific regulation, launches, and partnerships.

Industry should answer:
- what is happening in this industry right now?
- what macro forces are affecting it?
- what sector-specific developments matter independently of macro?
- what is the likely short-term directional pressure?

### 2. Exposure
This layer maps context into impact.

It answers:
- which industries are exposed to active macro themes?
- which tickers are exposed to industry and macro themes?
- what is the likely direction of pressure?

This layer should model transmission channels explicitly instead of assuming that context automatically implies a ticker recommendation.

### 3. Ticker setup
This layer estimates whether a specific ticker has a realistic short-horizon swing setup.

It should combine:
- macro context
- industry context
- ticker-specific catalysts
- ticker-specific sentiment
- technical setup
- volatility and timing
- liquidity and tradability

Typical components include:
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
- confidence
- tradeability status
- summary
- warnings
- setup family
- confidence components

### 4. Trade plan
This layer converts a valid ticker setup into a practical recommendation.

It should output:
- entry zone
- take profit
- stop loss
- horizon
- confidence
- risk/reward
- status

Entry, stop, and target should come from market structure and invalidation logic, not free-form summarization.

If a clean entry, stop, and target cannot be derived, the recommendation should be downgraded to `watchlist` or `no_action`.

## Pipeline stages

### A. Ingestion
Inputs include:
- financial news
- macro reporting
- industry publications
- official releases
- ticker/company news
- curated social posts

Social is secondary for macro and industry.

### B. Event extraction
This stage normalizes source items into reusable events or themes.

Its main purpose is to separate saliency from sentiment polarity.

### C. Context synthesis
This stage creates:
- macro context objects
- industry context objects

### D. Ticker setup evaluation
This stage scores near-term swing potential using context, catalysts, sentiment, and market structure.

It should evolve into a setup-aware evaluator rather than remain one generic scorer. Setup families such as continuation, breakout, mean reversion, catalyst follow-through, and sympathy or macro-exposure trades should stay distinguishable and later evaluable.

### E. Trade construction
This stage builds the final recommendation with entry, stop, target, warnings, and explicit `watchlist` / `no_action` outcomes when structure is not strong enough.

## Summary generation rules

### Macro summaries
Focus on:
- top salient events
- confirmed developments
- what changed
- which regions and markets are exposed

### Industry summaries
Focus on:
- industry-native developments
- macro spillovers
- likely short-term directional implications

### Ticker summaries
Focus on:
- catalyst
- exposure
- technical setup
- why the trade may work over the next few days
