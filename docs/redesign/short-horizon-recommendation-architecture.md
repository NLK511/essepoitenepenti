# Short-Horizon Recommendation Engine Redesign

**Status:** active redesign reference

## Purpose

This doc keeps the broader redesign model in one place.

Use the split redesign docs as the main active reference. Use this file when you want the full combined picture in one read.

Near-term, the redesign should be read as a short-horizon decision-support, candidate-ranking, and trade-framing system. Stronger predictive claims should wait for outcome and calibration evidence.

Recommendations should ultimately provide:

- direction
- entry zone
- take profit
- stop loss
- holding horizon
- confidence
- explicit risks and warnings

## Product objective

The app should answer the following sequence of questions:

1. What are the most important market-moving developments right now?
2. Which industries are exposed to those developments?
3. Which tickers are most likely to react within the next few days?
4. Is there a tradeable setup with a clear entry, stop loss, and take profit?

Near-term success for this architecture means:
- surfacing a manageable shortlist from broader watchlists
- improving operator decision quality
- producing explainable `no_action` outcomes when the edge is weak
- storing enough structure to evaluate whether recommendations actually work

## Non-negotiable operating principles

### 1. Observability and trust first
Trust and observability come first.

The app must:

- never use hidden fallbacks
- never silently substitute weaker data for stronger data
- never present degraded outputs as normal outputs
- always surface warnings when inputs are missing, stale, sparse, or potentially misleading
- allow uncertainty instead of pretending certainty

A useful rule:

> The app is allowed to be uncertain. It is not allowed to be falsely certain.

### 2. No hidden fallbacks
If a primary pipeline step fails, the app must say so explicitly.

Examples:

- if macro analysis is designed to be news-first and news ingestion fails, the output must say that it is degraded
- if industry analysis lacks industry-native coverage and only has macro spillover evidence, that limitation must be explicit
- if recommendation construction lacks a valid technical setup, the app should emit `watchlist` or `no_action` instead of forcing a trade plan

### 3. Practical recommendations only
The final output is not just analysis. It is an actionable recommendation when evidence is strong enough.

A recommendation must include:

- entry
- take profit
- stop loss
- confidence
- rationale
- risks

If the app cannot support those fields credibly, it should not emit a trade recommendation.

`No_action` and `watchlist` should be treated as first-class successful outputs, not as embarrassing fallbacks. Selective inaction is part of the product's credibility.

## High-level redesign

The app should be organized into four layers:

1. **Context**
2. **Exposure**
3. **Ticker setup**
4. **Trade plan**

### Layer 1: Context
This layer identifies what matters now.

It includes:

- macro context
- industry context

### Layer 2: Exposure
This layer maps context to industries and tickers.

It answers:

- which industries are affected?
- which tickers are exposed?
- in what direction?

### Layer 3: Ticker setup
This layer evaluates whether a specific ticker has a realistic short-horizon swing setup.

It combines:

- macro context
- industry context
- ticker-specific news
- ticker-specific sentiment
- technical setup
- volatility/liquidity/timing

This layer should eventually become setup-aware rather than acting like one generic weighted scorer. Different short-horizon setups should be distinguishable and evaluable, such as:
- continuation
- breakout
- mean reversion
- catalyst follow-through
- sympathy / sector read-through
- macro beneficiary / loser
- `no_action` because the evidence is conflicted or weak

### Layer 4: Trade plan
This layer converts a valid ticker setup into an actionable trade structure.

It outputs:

- entry zone
- stop loss
- take profit
- holding horizon
- confidence
- tradeability status

## Redefined role of macro, industry, and ticker analysis

## Macro analysis
Macro analysis should be a **saliency engine**, not primarily a sentiment engine.

Its job is to identify:

- major market-moving developments
- regime context
- regional exposure
- persistence vs escalation vs fading
- implications for the next few days

Examples:

- Iran conflict escalation
- oil upside pressure
- ECB restrictive stance
- European growth pressure
- risk-off regime

Macro should answer:

- what matters now?
- why does it matter?
- which regions and asset groups are exposed?
- is this new, intensifying, or fading?

Macro sentiment may still exist as a secondary signal, but it should not be the headline output.

### Macro source priority
Macro should be fed primarily by:

1. newspapers and financial newswires
2. official statements and central bank releases
3. high-credibility social posts as secondary support
4. broader social only as a supporting and clearly lower-trust signal

## Industry analysis
Industry analysis should not be derived only from macro.

It should combine:

1. **macro-linked drivers**
2. **industry-native developments**
3. **ticker read-throughs from important names in the industry**

Industry-native developments include:

- innovations
- product shifts
- technology trends
- major conferences
- pricing changes
- demand signals
- supply chain developments
- regulatory changes specific to the sector
- partnerships, launches, and sector-specific news

Industry should answer:

- what is happening inside this industry right now?
- what macro forces are affecting it?
- what sector-specific developments matter independently of macro?
- what is the likely short-term directional pressure?

### Industry source priority
Industry should be fed primarily by:

1. industry publications and trade press
2. sector/company news with read-through value
3. conference and product-cycle coverage
4. macro context as an important input
5. high-credibility social as supporting color, not the primary truth source

## Ticker analysis
Ticker analysis is where sentiment becomes more relevant.

Its purpose is to estimate whether a specific ticker is likely to move materially within a few days.

Ticker analysis should combine:

- macro exposure
- industry exposure
- ticker-specific catalysts
- ticker sentiment
- technical setup
- expected move size
- timing
- liquidity and tradability

Ticker should answer:

- is there a catalyst?
- is the ticker exposed to current macro or industry themes?
- is sentiment aligned or stretched?
- is the technical setup supportive now?
- does this look tradeable over a few days?

## Trade recommendation output
A final recommendation should be practical.

Example fields:

- ticker
- direction
- status (`long`, `short`, `watchlist`, `no_action`)
- entry_price_low
- entry_price_high
- take_profit_price
- stop_loss_price
- holding_period_days
- confidence
- risk_reward_ratio
- thesis_summary
- risks
- evidence_summary

The app should prefer `watchlist` or `no_action` over weak or forced trade ideas.

## Core pipeline design

## Stage A: Ingestion
Ingestion should be source-aware and store raw data in a proper database.

Inputs:

- general financial news
- macro-specific reporting
- industry-specific publications
- official releases
- ticker/company news
- curated social posts

Social is secondary for macro and industry, not primary.

The architecture should optimize for evidence quality, not just source count. That means official releases, top-tier market reporting, trade press, and company statements should eventually outrank lower-value syndicated commentary or noisy social chatter.

All ingestion results should preserve:

- provider
- timestamps
- source type
- raw content
- dedupe metadata
- fetch diagnostics
- failures and warnings

## Stage B: Event extraction
This stage normalizes raw source items into events/themes.

Examples of macro events:

- `geopolitics_middle_east_escalation`
- `oil_supply_shock_risk`
- `ecb_restrictive_bias`
- `european_growth_pressure`

Examples of industry events:

- `semiconductor_ai_conference_tailwind`
- `airline_cost_pressure_from_oil`
- `defense_procurement_acceleration`
- `retail_inventory_normalization`

Each event should store:

- scope
- label
- saliency
- novelty
- confidence
- started_at / detected_at
- affected regions
- affected industries
- affected tickers where applicable
- linked evidence items

This stage is critical because it separates **saliency** from **sentiment polarity**.

## Stage C: Context synthesis
This stage creates context objects from extracted events.

### Macro context object
Should include:

- active themes
- regime tags
- saliency score
- confidence
- summary text
- change notes
- evidence summary
- warnings and missing inputs

### Industry context object
Should include:

- active drivers
- direction
- saliency score
- confidence
- linked macro themes
- linked industry-native themes
- summary text
- warnings and missing inputs

## Stage D: Ticker setup evaluation
This stage evaluates near-term swing potential for each ticker.

Suggested components:

- macro_exposure_score
- industry_alignment_score
- ticker_catalyst_score
- ticker_sentiment_score
- technical_setup_score
- expected_move_score
- timing_score
- liquidity_score
- execution_quality_score

Outputs:

- expected_direction
- swing_probability
- confidence
- tradeability status
- ticker summary
- warnings
- setup_family
- confidence_components

### Design constraint for this stage
This stage should not remain a monolithic score forever. It should become possible to inspect and evaluate separate components such as:
- context confidence
- directional confidence
- catalyst confidence
- technical clarity
- execution clarity
- data-quality caps

Those components should support both operator explanation and later confidence calibration.

## Stage E: Trade construction
This stage builds the actual recommendation.

### Entry
Entry should come from market structure, not from free-form language.

Examples:

- breakout above recent resistance
- pullback into support or retest zone
- reclaim level after catalyst

### Stop loss
Stop loss should come from invalidation logic plus volatility buffer.

Examples:

- below swing low
- below breakout level minus ATR buffer
- above swing high for shorts

### Take profit
Take profit should come from expected move and structure.

Examples:

- next resistance/support
- ATR multiple
- minimum acceptable risk/reward threshold

If a clean entry/stop/target cannot be derived, the setup should be downgraded to `watchlist` or `no_action`.

## Data and persistence

## Database choice
The app should move to a proper database, with PostgreSQL as the target.

Why PostgreSQL:

- reliable persistence for production workflows
- good support for relational data and JSONB
- indexing and time-based querying
- strong migration support
- suitable for historical analytics and backtesting

## Storage requirements
The system should store at least:

### Raw source items
- news articles
- social posts
- official statements
- metadata and dedupe hashes
- fetch diagnostics

### Extracted events
- normalized macro/industry/ticker events
- saliency/confidence/novelty
- linked evidence

### Context snapshots
- macro context snapshots
- industry context snapshots
- summaries
- active themes
- warnings and status

### Ticker signal snapshots
- technical features
- sentiment features
- exposure scores
- catalysts
- confidence breakdown

### Recommendations
- entry, stop, target
- horizon
- confidence
- thesis
- risks
- status

### Recommendation outcomes
- whether TP or SL was hit
- realized outcome
- MFE/MAE
- fixed-horizon returns
- realized holding period
- direction correctness
- confidence calibration bucket
- setup-family attribution
- notes for evaluation and improvement

## Proposed schema direction

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
Join table between events and evidence items.

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

## Observability model

## Shared status field
Every major object should carry a status field:

- `ok`
- `partial`
- `degraded`
- `failed`

This should apply to:

- ingestion runs
- macro context snapshots
- industry context snapshots
- ticker signal snapshots
- recommendation plans

## Shared diagnostics fields
Every major object should expose diagnostics such as:

- warnings
- missing_inputs
- source_failures
- evidence_counts
- source_breakdown
- confidence_caps
- suppression_reasons

Warnings must be first-class data, not just logs.

## Examples of explicit warnings

### Macro warnings
- primary news sources unavailable
- only social evidence present
- sparse macro evidence
- stale data
- event extraction low confidence

### Industry warnings
- no industry-native evidence found
- industry context derived mostly from macro spillover
- conference/trade press coverage unavailable
- sparse evidence for current window

### Recommendation warnings
- recommendation generated without fresh macro context
- industry context incomplete
- technical setup stale
- entry/stop/target based on weak structure
- risk/reward below preferred threshold

## Source hierarchy rules

### Macro
Priority order:

1. newspaper / financial newswire / official sources
2. high-credibility social
3. broader social as support only

### Industry
Priority order:

1. industry publications / sector reporting
2. company and sector read-through news
3. macro context
4. high-credibility social
5. broader social as support only

### Ticker
Priority order:

1. ticker-specific news/catalysts
2. price action and technical setup
3. macro/industry context
4. ticker-specific sentiment

## Summary generation rules

### Macro summaries
Should primarily summarize:

- top salient macro events
- official/news-confirmed developments
- what changed
- which regions/markets are exposed

Not just sentiment labels.

### Industry summaries
Should primarily summarize:

- industry-native developments
- important macro spillovers
- likely short-term directional implications

### Ticker summaries
Should primarily summarize:

- catalyst
- exposure
- technical setup
- why the trade may work over the next few days

## Confidence philosophy
Confidence should be traceable and component-based.

It should reflect:

- source quality
- evidence coverage
- agreement across sources
- freshness
- clarity of direction
- technical setup quality
- quality of entry/stop/target construction

Confidence must be reduced or capped if:

- primary sources are missing
- evidence is sparse
- upstream context is degraded
- the setup is not clean enough to trade

Confidence should also be understood as something that must later be calibrated against outcomes. A persuasive-looking confidence number is not enough. The architecture should support evaluating whether, for example, 70% confidence recommendations actually outperform 55% confidence recommendations, and under which setup families or market regimes.

## Recommendation states
To avoid forcing weak ideas, recommendations should support:

- `long`
- `short`
- `watchlist`
- `no_action`

`watchlist` and `no_action` are valid, useful outputs.

## Migration direction

### Phase 1: Freeze additional complexity in current macro/industry sentiment summaries
Keep the current system stable, but stop extending the sentiment-first approach for macro and industry.

### Phase 2: Introduce new context models beside sentiment snapshots
Add:

- macro context objects
- industry context objects
- event extraction outputs

Do not remove the current structures yet.

### Phase 3: Move macro and industry jobs to saliency-first logic
Macro and industry jobs should become context jobs driven primarily by news and structured event extraction.

### Phase 4: Make recommendation outcomes first-class
This phase is now partially delivered: recommendation plans persist deterministic outcomes with horizon returns, excursion metrics, direction correctness, confidence buckets, and setup-family capture.

What remains is to use those stored outcomes for confidence calibration and setup-family-aware engine improvement.

### Phase 5: Feed context into redesign-native ticker setup evaluation
Ticker scoring should consume:

- macro context
- industry context
- ticker-specific catalysts
- technical setup
- ticker sentiment

This stage should also replace legacy deep-analysis internals with a redesign-native ticker engine.

### Phase 6: Add setup-aware recommendation construction
Recommendation construction should classify and handle distinct setup families rather than treating all candidates as one generic scorer output.

### Phase 7: Retire macro/industry sentiment as the primary concept
Macro and industry may still keep sentiment as a sub-signal, but saliency/context becomes the primary product surface.

## Final target statement
The app should become:

- a **macro context detector**
- an **industry transmission and industry-native trend mapper**
- a **ticker swing setup evaluator**
- a **practical trade recommendation engine**

Near-term, that should be interpreted as:
- a strong operator-facing market analysis and shortlist system
- an explainable trade-framing engine
- a recommendation process whose quality can be truth-tested against stored outcomes

Only after that should it be treated as a validated short-horizon predictive engine in the stronger sense.

All of that should operate under strict observability rules:

- no hidden fallbacks
- explicit warnings
- clear degraded states
- stored diagnostics
- no false confidence

## See also

- `README.md` — redesign doc map
- `principles.md` — redesign rules
- `target-architecture.md` — layered redesign shape
- `transmission-modeling-spec.md` — context transmission rules
- `calibration-governance-spec.md` — outcome-aware confidence governance
- `setup-family-playbook.md` — setup-family-specific plan behavior
- `data-model-and-persistence.md` — redesign persistence direction
