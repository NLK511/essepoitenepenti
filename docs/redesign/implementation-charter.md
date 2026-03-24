# Implementation Charter

## Purpose

This document locks the implementation-level defaults for the redesign.

It exists so development can proceed with minimal ambiguity while staying aligned with the product objective: generate practical short-horizon recommendations that can help predict swings likely to happen within the next day, week, or month.

## Core product objective

The app should produce recommendation outputs for curated watchlists of tickers, using macro context, industry context, ticker-specific catalysts, sentiment, and technical structure.

The final recommendation states are:

- `long`
- `short`
- `no_action`

The system should avoid arbitrary trade levels. Entry, stop loss, and take profit should only be generated when the combined signal is directionally strong enough and market structure supports a credible trade plan.

## Locked implementation decisions

## 1. Horizons
The system supports three strategy horizons:

- `1d`
- `1w`
- `1m`

These are treated as different parameter profiles within the same engine, not as completely separate systems.

Implications:

- freshness weighting changes by horizon
- technical setup logic changes by horizon
- target and stop construction changes by horizon
- confidence scoring may differ by horizon
- evaluation scheduling may differ by horizon

## 2. Watchlists
Watchlists are first-class objects.

They are:

- curated by the user
- persisted in the app database
- allowed to exist in multiple copies for different purposes
- allowed to be split by region and exchange

Examples:

- US large caps
- EU industrials
- Milan exchange swing names
- short-term high-volatility watchlist

### Watchlist-level settings
Each watchlist should be able to store configuration such as:

- name
- description
- region
- exchange
- timezone
- default horizon
- whether short recommendations are allowed
- whether evaluation timing should be optimized for the exchange
- optional scheduling preferences

Equities are the preferred instrument type, but ETFs are allowed. The design should not hard-block ETFs.

## 3. Recommendation actions
The only recommendation actions are:

- `long`
- `short`
- `no_action`

### Meaning of `no_action`
`no_action` does not simply mean low evidence.

It means that the combined signal from all relevant components does not provide a sufficiently strong directional edge.

Relevant components include, where available:

- technical structure
- macro context
- industry context
- ticker-specific catalysts
- ticker sentiment
- other timing or tradability signals

When the result is `no_action`:

- no entry zone should be generated
- no stop loss should be generated
- no take profit should be generated

This prevents arbitrary trade levels from being emitted when the directional case is weak or conflicted.

## 4. Recommendation output policy
The system should still emit a stored evaluation result for every analyzed ticker.

That result should include:

- action (`long`, `short`, `no_action`)
- confidence percentage
- rationale summary
- warnings
- diagnostics
- supporting signal breakdown

This is required for:

- observability
- later evaluation
- backtesting
- algorithm improvement

## 5. Confidence representation
Confidence should be exposed as a **percentage**.

Implementation note:

- internal scoring may still use normalized values
- stored and displayed outputs should expose a percentage representation

Confidence should remain distinct from the action itself.

A ticker can have usable data and moderate confidence in the analysis process yet still result in `no_action` if the directional edge is not strong enough.

## 6. Short-selling policy
Whether shorts are allowed should be a **watchlist-level toggle**.

Suggested field:

- `allow_shorts: true | false`

If shorts are disabled for a watchlist, the engine should not emit `short` recommendations for names in that watchlist.

## 7. API-call-saving evaluation flow
The system should use a staged evaluation flow to reduce expensive external calls.

### Stage 1: cheap scan
Run a lightweight evaluation across all tickers in a selected watchlist.

This should favor:

- cached macro context
- cached industry context
- cheap technical signals
- cached or cheap headline-based news signals
- locally available metadata

The goal is to compute a preliminary signal such as:

- attention score
- directional bias
- whether deep analysis is justified

### Stage 2: deep analysis
Only shortlisted names should receive deeper, more expensive analysis.

This may include:

- richer ticker news retrieval
- ticker social analysis if enabled
- deeper technical structure evaluation
- entry/stop/target construction

This staged model is required for efficiency.

## 8. Source policy
The redesign should favor broad, free, and publicly accessible news sources.

For macro and industry context, even headline-only access is useful if the source quality is good.

Target source classes include:

- broad financial newspapers
- major free/public financial headlines
- official statements
- trade and industry publications
- public snippets from high-quality providers

### Restrictions
Implementation should avoid depending on brittle paywall scraping.

The system should prefer:

- publicly accessible headlines
- public snippets
- public metadata
- official/public feeds where available

The app must not invent missing article content.

If only headlines are available, downstream analysis must be aware that the evidence is headline-only.

## 9. Source hierarchy
### Macro
Primary inputs:

1. newspapers and financial newswires
2. official statements and macro releases
3. high-credibility social as support
4. broader social as secondary support only

### Industry
Primary inputs:

1. industry publications and trade press
2. sector and company news with industry read-through value
3. conference, innovation, and product-cycle coverage
4. macro context
5. high-credibility social as support

### Ticker
Primary inputs:

1. ticker-specific catalysts and news
2. price action and technical structure
3. macro and industry context
4. ticker-specific sentiment

## 10. Context pipeline
The app should use one shared context ingestion and event pipeline, which then produces:

- macro context outputs
- industry context outputs

This avoids duplicated ingestion and helps reduce unnecessary API calls.

## 11. Scheduling policy
Watchlists may be split by region and exchange so that analysis can run at better moments of the day.

The design should support an option such as:

- `optimize_evaluation_timing = true`

When enabled, the scheduler should be allowed to evaluate the watchlist at times that better match the exchange context of its tickers.

Examples:

- evaluate EU names during or around EU trading hours
- evaluate US names during or around US trading hours

The precise scheduling policy can evolve, but the data model and service design must support this from the start.

## 12. Data persistence
All major inputs and outputs should be stored in the database.

This includes:

- watchlists and watchlist items
- source items
- fetch diagnostics
- detected events
- macro context snapshots
- industry context snapshots
- ticker evaluations
- recommendations
- recommendation outcomes

## 13. Observability rules
Observability remains a hard rule.

The app must:

- never use hidden fallbacks
- explicitly show degraded states
- store warnings and diagnostics as structured data
- preserve source provenance
- avoid false confidence

### Required structured diagnostics
Major objects should expose fields such as:

- `status`
- `warnings`
- `missing_inputs`
- `source_breakdown`
- `source_failures`
- `confidence_caps`
- `suppression_reasons`

## 14. Migration policy
Migration can be disruptive.

There is no requirement to keep the old macro/industry sentiment model running in parallel while the new architecture is introduced.

That means development may:

- replace macro/industry sentiment-first concepts aggressively
- prioritize new context models over backward compatibility
- simplify or remove convoluted intermediate designs

## 15. Immediate design consequences
The next implementation work should assume:

- macro is saliency-first
- industry combines macro and industry-native developments
- ticker analysis is setup-oriented
- recommendations are practical only when a directional edge is present
- `no_action` produces no trade levels
- every evaluation is stored for learning and backtesting

## Open items not yet numerically fixed
The following still require later tuning rather than immediate architectural decisions:

- exact confidence thresholds for long/short vs `no_action`
- exact attention-score threshold for deep analysis
- exact liquidity and risk/reward thresholds
- exact best-moment-of-day scheduling rules per exchange

These are parameter-tuning questions, not blockers for architecture and development.
