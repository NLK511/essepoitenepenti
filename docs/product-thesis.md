# Product Thesis

**Status:** current behavior

## What this product is

Trade Proposer App is an operator-facing system for generating, inspecting, evaluating, and improving trade recommendations inside one product boundary.

Near-term, it should be read as an explainable market-analysis, candidate-ranking, and trade-framing system. Stronger predictive claims should wait for outcome and calibration evidence.

The point is to keep execution, review, diagnostics, and outcome tracking in one place.

## Core goal

The app should answer this sequence:
1. what are the most important market-moving developments right now?
2. which industries are exposed to those developments?
3. which tickers are most likely to react within the next few days?
4. is there a tradeable setup with a clear entry, stop, and target?

The goal is not to maximize signal count.

The goal is to produce recommendations that are:
- inspectable
- reproducible
- operationally manageable
- honest about degraded inputs

The app should prefer visible uncertainty over hidden guesswork.

## Governing principle

### Signal integrity over cosmetic completeness

If an input is missing, stale, or failing, the app should say so explicitly.

That means:
- missing data becomes warnings or neutral values
- stale shared context remains visible in health/preflight
- provider failures remain visible in diagnostics
- fallback behavior must not look equivalent to healthy input
- uncertainty is allowed, but false certainty is not allowed

### Practical recommendation standard

A practical recommendation should include:
- direction
- entry zone
- take profit
- stop loss
- horizon
- confidence
- rationale
- risks

If the system cannot support those fields credibly, it should not force a trade. `watchlist` and `no_action` are first-class successful outputs because selective inaction is part of recommendation quality.

## Product shape

The app should feel like one place for this workflow:
- define watchlists and jobs
- run proposal generation
- inspect runs, plans, and outcomes
- review shared context
- evaluate outcomes
- optimize weights
- read docs in-product

The operator should not have to leave the app to understand what happened.

## Strategic priority order

Work should be prioritized in this order:
1. **Reliability**
2. **Observability**
3. **Security and credential lifecycle**
4. **Evidence of recommendation quality**
5. **Feature expansion**

## Source hierarchy

Use source quality explicitly:
- macro context should prioritize financial newswires, major newspapers, official statements, and central-bank releases; social is secondary support
- industry context should prioritize trade press, sector/company read-through, product-cycle coverage, and macro context; social is secondary support
- ticker analysis should prioritize ticker-specific news/catalysts, price action, macro/industry context, and ticker sentiment

## What to avoid

- speculative integrations as near-term priorities
- duplicate roadmap language across many docs
- fallback heuristics that hide degraded inputs
- forced recommendations when `watchlist` or `no_action` is more honest
- multi-user expansion before the single-user model is operationally solid

## Standard for future decisions

A proposed feature is a good fit if it improves at least one of:
- operator trust
- reproducibility
- diagnosability
- workflow reliability
- measured recommendation quality

A feature is a poor fit if it mainly adds complexity, provider surface area, or narrative polish without improving those outcomes.

## See also

- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `roadmap.md`
- `architecture.md`
