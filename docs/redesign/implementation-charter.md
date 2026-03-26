# Implementation Charter

## Purpose

This document locks the implementation-level defaults for the redesign.

More detailed supporting specs now live alongside this charter for transmission modeling, calibration governance, setup-family behavior, measured success criteria, and legacy convergence.

It exists so development can proceed with minimal ambiguity while staying aligned with the product objective: generate practical short-horizon recommendations that can help identify likely swings within the next day, week, or month.

This document also intentionally sets realism constraints on the redesign. The app should be built first as a high-quality operator decision-support and candidate-ranking system with explicit diagnostics, selective `no_action` behavior, and measurable recommendation outcomes. It should not be presented internally as a proven predictive engine until the redesign path has demonstrated real calibration and outcome quality through stored evaluation data.

## Core product objective

The app should produce recommendation outputs for curated watchlists of tickers, using macro context, industry context, ticker-specific catalysts, sentiment, and technical structure.

The realistic product target is:
- surface a manageable shortlist from a broader watchlist
- explain why each name was shortlisted, rejected, or downgraded to `no_action`
- construct actionable trade plans only when the evidence is strong enough
- create a stored feedback loop so the quality of those plans can be measured and improved

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

### Practical product stance
The redesign should optimize for decision quality and inspectability before claiming broad predictive skill.

Near-term success means:
- better operator triage
- better candidate ranking
- better trade framing
- better suppression of weak or conflicted setups

It does **not** yet mean the system should be treated as a fully validated few-day swing predictor across all names, sectors, and regimes.

## 5. Confidence representation
Confidence should be exposed as a **percentage**.

Implementation note:

- internal scoring may still use normalized values
- stored and displayed outputs should expose a percentage representation

Confidence should remain distinct from the action itself.

A ticker can have usable data and moderate confidence in the analysis process yet still result in `no_action` if the directional edge is not strong enough.

### Confidence design consequences
Confidence should ultimately be decomposable rather than treated as one opaque number. The redesign should converge toward separate components such as:

- context confidence
- directional confidence
- catalyst confidence
- technical clarity
- execution clarity
- data-quality caps

This keeps confidence honest and makes it easier to evaluate which parts of the engine actually add value.

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

### Cheap-scan caution
Cheap scan is a triage layer, not the source of truth for trade quality.

It should be used to reduce cost and focus attention, but it should not be overinterpreted as the app's main edge. The redesign should continue to assume that event-sensitive, catalyst-driven, and regime-specific setups may require deeper evidence than trend or momentum features alone can provide.

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

### Evidence-quality rule
`News-first` is not enough on its own. The redesign should increasingly rank evidence by source quality and market usefulness, distinguishing between:

- official or primary releases
- top-tier market reporting
- trade and industry press
- company statements and filings
- lower-value syndicated commentary
- social confirmation and color

The app should avoid treating all news items as equal evidence. Source class, freshness, specificity, and direct market relevance should all matter to context confidence and recommendation confidence.

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

### Event-centric expectation
Macro and industry context should evolve toward explicit event objects and saliency ranking rather than remaining mostly keyword- or polarity-driven.

The target shape is that the pipeline can identify and persist things such as:
- event type
- event title
- event timestamp or active window
- saliency
- confidence
- affected regions
- affected industries
- evidence links and source classes
- expected transmission window

Context snapshots should then explain what matters now, what changed since the previous run, and which sectors or tickers appear exposed.

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
- recommendation plans
- recommendation outcomes

### Implemented groundwork and first write path
The redesign now has an initial persisted target surface in the app schema.

Implemented models and tables:
- `MacroContextSnapshot` → `macro_context_snapshots`
- `IndustryContextSnapshot` → `industry_context_snapshots`
- `TickerSignalSnapshot` → `ticker_signal_snapshots`
- `RecommendationPlan` → `recommendation_plans`
- `RecommendationPlanOutcome` → `recommendation_outcomes`

Implemented support around them:
- Alembic migration `0013_context_and_recommendation_models`
- repository layer for creating and listing the new objects
- read-only API routes for inspecting them
- run-scoped API/UI visibility for redesign objects
- standalone browse pages for ticker signals and recommendation plans

Implemented write-path migration so far:
- watchlist-backed proposal jobs now use cheap-scan → shortlist → deep-analysis orchestration
- every scanned watchlist ticker now gets a persisted `TickerSignalSnapshot` and `RecommendationPlan`
- only actionable deep-analysis outputs still create legacy `Recommendation` rows for compatibility

Current limitation:
- manual ticker proposal jobs still use the legacy path
- macro and industry context objects are now written during refresh runs through event-ranked, news-first transitional writers that prioritize official/trade/major sources, but those writers are still heuristic rather than a mature multi-step event pipeline
- watchlist deep analysis now has a dedicated service boundary and native watchlist execution path, but its underlying analysis still depends partly on legacy proposal-engine internals and payload conventions

### Outcome-tracking requirement
The redesign should treat stored recommendation outcomes as the main truth-testing mechanism for whether the engine is improving.

That recommendation-plan path now records and evaluates measures such as:
- entry touched or not
- stop touched or not
- take-profit touched or not
- return after fixed horizons
- maximum favorable excursion
- maximum adverse excursion
- realized holding period
- direction correctness
- confidence calibration buckets
- setup-family capture

Further analytical redesign work should be steered by those outcomes rather than by subjective plausibility alone.

### Current outcome-tracking limitation
Outcome persistence now exists, but the app still needs to use those stored results more intelligently.

What remains unfinished is:
- generation-time setup-family classification rather than mostly evaluation-time carry-through
- confidence calibration against realized outcomes
- stronger outcome-aware recommendation-engine refinement driven by measured setup-family performance

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

- macro is saliency-first and increasingly event-centric
- industry combines macro transmission and industry-native developments
- ticker analysis is setup-oriented rather than generic sentiment aggregation
- recommendations are practical only when a directional edge is present
- `no_action` is a first-class success state when the edge is weak, conflicted, or untrustworthy
- every evaluation is stored for learning and backtesting
- the app should optimize for selective, inspectable decision quality before making strong predictive claims

## 16. Current redesign status
Completed in the redesign track so far:
- watchlists now carry trading and scheduling metadata (`description`, `region`, `exchange`, `timezone`, `default_horizon`, `allow_shorts`, `optimize_evaluation_timing`)
- watchlist evaluation policy and timezone-aware scheduling are implemented, and policy details are now surfaced directly in watchlist and run-detail operator workflows
- watchlist-backed proposal jobs now run through cheap-scan to shortlist to deep-analysis orchestration
- a dedicated cheap-scan signal model now drives shortlist selection
- the new persistence-layer foundations for context snapshots, ticker signals, and recommendation plans are in place
- ticker signals and recommendation plans are browseable through run detail, run-scoped APIs, and dedicated pages
- run artifacts now record shortlist rules, rejection counts, and per-ticker shortlist decisions
- shortlist reasoning is surfaced directly in run detail and ticker-signal operator views, now including lane selection, catalyst proxy scores, and transmission context
- macro and industry refresh runs now also write first-generation context snapshots into the redesign tables
- those context writers now prefer primary news evidence, with social evidence used as secondary support
- watchlist deep analysis now runs through a dedicated `TickerDeepAnalysisService` boundary
- that deep-analysis path now executes natively inside `TickerDeepAnalysisService` for watchlist orchestration instead of delegating normal analysis to `ProposalService.generate(...)`
- `RecommendationPlan` now has first-class persisted outcome tracking through `recommendation_outcomes`, including fixed-horizon returns, excursion metrics, direction correctness, confidence buckets, and latest-outcome API exposure
- watchlist-backed `RecommendationPlan` generation now writes setup-family-aware signal breakdowns and decomposed confidence components into persisted redesign payloads
- recommendation outcomes can now be summarized by confidence bucket and setup family through API/UI calibration views for operator review
- watchlist-backed plan generation now applies early calibration-aware action-threshold adjustments using stored setup-family and confidence-bucket outcome slices
- recommendation-plan operator workflows now include baseline cohort comparisons against simple high-confidence, cheap-scan-attention, momentum-lane, and catalyst-lane heuristics
- calibration reporting now includes horizon, transmission-bias, context-regime, and horizon-plus-setup-family slices for redesign-native operator review, marks slice sample quality explicitly, and watchlist-backed action gating now consumes those richer slices with bounded, sample-aware threshold adjustments when setting effective confidence thresholds
- ticker deep analysis now emits richer transmission summaries, including primary drivers, conflict flags, and expected transmission windows, uses a redesign-native internal feature/context pipeline, and watchlist orchestration reserves a small catalyst/event shortlist lane in addition to the main technical lane

Not yet complete:
- a richer event-extraction pipeline beyond the current heuristic event-ranking and source-priority layer
- a fuller redesign-native ticker-analysis and recommendation-engine path with less dependence on legacy proposal-engine internals and payload conventions
- confidence calibration and outcome-driven refinement for the new recommendation-plan path
- migration or retirement strategy for the remaining legacy recommendation and sentiment-snapshot paths

Practical meaning:
- the redesign is now well past the purely conceptual stage
- watchlist-backed proposal runs already exercise the first real redesign write path, refresh runs populate context tables, and shortlist reasoning is operator-visible without JSON spelunking
- the app can realistically become a strong operator decision-support and candidate-ranking system in the near term
- it should not yet be treated as a validated universal few-day swing predictor until recommendation outcomes and confidence calibration show real evidence of edge
- the next best work is no longer more persistence scaffolding; it is stronger evidence extraction, redesign-native ticker analysis, setup-aware recommendation logic, and evaluation of recommendation-plan outcomes

## Open items not yet numerically fixed
The following still require later tuning rather than immediate architectural decisions:

- exact confidence thresholds for long/short vs `no_action`
- exact attention-score threshold for deep analysis
- exact liquidity and risk/reward thresholds
- exact best-moment-of-day scheduling rules per exchange

These are parameter-tuning questions, not blockers for architecture and development.
