# Principles

**Status:** active redesign reference

## Purpose

This doc defines the main product and engineering rules for the redesign.

Near-term, the redesign is a short-horizon decision-support and trade-planning system. It should not be treated as a broadly validated predictive engine until outcomes and calibration support that claim.

## Product objective

The app should answer this sequence:
1. what are the most important market-moving developments right now?
2. which industries are exposed to those developments?
3. which tickers are most likely to react within the next few days?
4. is there a tradeable setup with a clear entry, stop, and target?

## Core rule: observability and trust first

This is non-negotiable.

The app must:
- never use hidden fallbacks
- never silently substitute weaker inputs for stronger ones
- never present degraded outputs as normal outputs
- always surface warnings when outputs may be missing, sparse, stale, partial, or misleading
- allow uncertainty instead of pretending certainty

> The app is allowed to be uncertain. It is not allowed to be falsely certain.

## Practical recommendation standard

The final output is only a practical recommendation when evidence is strong enough.

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
Prioritize:
1. newspapers and financial newswires
2. official statements and central-bank releases
3. high-credibility social as secondary support
4. broader social only as supporting color

### Industry
Prioritize:
1. industry publications and trade press
2. sector or company news with read-through value
3. conference and product-cycle coverage
4. macro context as an important input
5. high-credibility social as supporting color

### Ticker
Prioritize:
1. ticker-specific news and catalysts
2. price action and technical setup
3. macro and industry context
4. ticker-specific sentiment

## Context principles

### Macro is saliency-first
Macro should identify:
- major market-moving developments
- regime context
- regional exposure
- persistence vs escalation vs fading
- likely implications over the next few days

Macro sentiment can remain as a secondary signal, but it should not be the main output.

### Industry is macro-plus-native
Industry analysis should combine:
1. macro-linked drivers
2. industry-native developments
3. read-throughs from important names in the industry

Industry-native developments include product shifts, technology trends, conferences, pricing changes, demand signals, supply-chain changes, and sector-specific regulation.

### Ticker analysis is swing-oriented
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

Supported states:
- `long`
- `short`
- `watchlist`
- `no_action`

## Canonical operator truth

For the active proposal workflow, the main operator review path should be:
1. `TickerSignalSnapshot`
2. `RecommendationPlan`
3. `RecommendationPlanOutcome`

Legacy `Recommendation` rows may still exist for compatibility, but they should not be the main internal truth for the current workflow.

## Confidence philosophy

Confidence should be component-based and traceable.

It should reflect:
- source quality
- evidence coverage
- source agreement
- freshness
- directional clarity
- technical setup quality
- execution quality of entry, stop, and target

Confidence must be reduced or capped when:
- primary sources are missing
- evidence is sparse
- upstream context is degraded
- technical structure is weak
- the recommendation is not robust enough to trade

The redesign should keep confidence explicit enough to calibrate later against outcomes, including components such as context confidence, directional confidence, catalyst confidence, technical clarity, execution clarity, and data-quality caps.
