# Principles

**Status:** active redesign reference

## Purpose

This doc defines the product and engineering rules for the redesign.

Near-term, the redesign is about a short-horizon decision-support and trade-planning system. It should not be treated as a broadly validated predictive engine until outcomes and calibration support that claim.

## Product objective

The app should answer this sequence:

1. What are the most important market-moving developments right now?
2. Which industries are exposed to those developments?
3. Which tickers are most likely to react within the next few days?
4. Is there a tradeable setup with a clear entry, stop loss, and take profit?

## Observability and trust first

This is a non-negotiable rule.

The app must:

- never use hidden fallbacks
- never silently substitute weaker inputs for stronger inputs
- never present degraded outputs as normal outputs
- always surface warnings when outputs may be missing, sparse, stale, partial, or misleading
- allow uncertainty instead of pretending certainty

A useful rule:

> The app is allowed to be uncertain. It is not allowed to be falsely certain.

## No hidden fallbacks

If a primary pipeline step fails, the app must say so explicitly.

Examples:

- if macro analysis is designed to be news-first and news ingestion fails, the macro output must be marked degraded
- if industry analysis lacks industry-native evidence and is mostly inferred from macro spillover, that limitation must be stated clearly
- if technical structure is too weak to define a credible entry, stop loss, and take profit, the app should emit `watchlist` or `no_action`

## Practical recommendation standard

The final output is not just an analysis artifact. It is a practical recommendation when evidence is strong enough.

A valid recommendation should include:

- direction
- entry zone
- take profit
- stop loss
- horizon
- confidence
- rationale
- risks

If the system cannot support those fields credibly, it should not force a recommendation.

`watchlist` and `no_action` are first-class successful outputs because selective inaction is part of recommendation quality.

## Source hierarchy

### Macro
Macro should be fed primarily by:

1. newspapers and financial newswires
2. official statements and central-bank releases
3. high-credibility social posts as secondary support
4. broader social only as supporting color

### Industry
Industry should be fed primarily by:

1. industry publications and trade press
2. sector/company news with read-through value
3. conference and product-cycle coverage
4. macro context as an important input
5. high-credibility social as supporting color

### Ticker
Ticker analysis should prioritize:

1. ticker-specific news and catalysts
2. price action and technical setup
3. macro and industry context
4. ticker-specific sentiment

## Macro is saliency-first

Macro analysis should identify:

- major market-moving developments
- regime context
- regional exposure
- persistence versus escalation versus fading
- implications for the next few days

Macro sentiment may remain as a secondary signal, but it should not be the main output.

## Industry is macro-plus-native

Industry analysis must combine:

1. macro-linked drivers
2. industry-native developments
3. read-throughs from important names in the industry

Industry-native developments include:

- innovations
- product shifts
- technology trends
- major conferences
- pricing changes
- demand signals
- supply-chain developments
- regulatory changes specific to the sector

## Ticker analysis is swing-oriented

Ticker analysis should estimate whether a specific ticker is likely to move materially within a few days.

It should combine:

- macro exposure
- industry exposure
- ticker-specific catalysts
- ticker sentiment
- technical setup
- expected move size
- timing
- liquidity and tradability

## Recommendation states

The app should not force every ticker into a trade recommendation.

Supported states should include:

- `long`
- `short`
- `watchlist`
- `no_action`

`watchlist` and `no_action` are valid outputs.

## Canonical operator truth

For redesign-native proposal workflows, the canonical operator review path should be:

1. `TickerSignalSnapshot`
2. `RecommendationPlan`
3. `RecommendationPlanOutcome`

Legacy `Recommendation` rows may still exist for compatibility, but they should not remain the primary internal truth for redesigned proposal workflows.

## Confidence philosophy

Confidence should be component-based and traceable.

It should reflect:

- source quality
- evidence coverage
- source agreement
- freshness
- clarity of direction
- technical setup quality
- execution quality of entry/stop/target

Confidence must be reduced or capped when:

- primary sources are missing
- evidence is sparse
- upstream context is degraded
- technical structure is weak
- the recommendation is not robust enough to trade

Confidence should also be built so it can later be calibrated against outcomes. The redesign should converge toward explicit confidence components such as context confidence, directional confidence, catalyst confidence, technical clarity, execution clarity, and data-quality caps.
