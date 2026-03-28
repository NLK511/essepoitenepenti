# Recommendation Methodology

**Status:** canonical recommendation logic

This document answers one question:
> how does the app produce recommendation outputs?

The point of the methodology is not to pile on more signals. The point is to produce recommendations that are:
- reproducible
- inspectable
- clear about degraded inputs

Right now the methodology should be read as a decision-support and candidate-ranking process. It is not yet proof of broad predictive skill.

## Core rule

The main rule is signal integrity:
- missing or stale inputs should become warnings or neutral values
- degraded provider coverage should stay visible in diagnostics
- fallback behavior should not be presented as equal to healthy input

## Pipeline overview

### Current production pipeline
`WatchlistOrchestrationService` is the active proposal-generation execution path.

For each proposal run, the pipeline:
1. resolves the effective watchlist or manual ticker wrapper
2. runs cheap scan across the candidate set
3. selects a shortlist using explicit attention/confidence/catalyst rules
4. runs `TickerDeepAnalysisService` for shortlisted names
5. fetches recent OHLC price history through `yfinance`
6. computes technical indicators and context-enriched features with `pandas`
7. loads the latest valid shared macro and industry artifacts for the ticker’s mapped profile
8. builds recommendation plans, diagnostics, and structured audit payloads
9. persists ticker signals, recommendation plans, run summaries, and run artifacts

`ProposalService` still exists as a lower-level analysis helper used by deep analysis for price history, feature engineering, news/context enrichment, and structured diagnostics, but it is no longer the main proposal-run execution path.

If an input is unavailable, the system stores that fact and falls back to warnings or neutral values.

### Current redesign path
The redesign path now persists:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`

Watchlist-backed proposal jobs use a staged flow:
1. cheap scan across the watchlist
2. shortlist selection
3. deep analysis for shortlisted names through `TickerDeepAnalysisService`
4. persistence of ticker signals and recommendation plans

## App-native independence and data layers used by the methodology

### 1. Market data
The app uses `yfinance` for price history and volume.

That data is used both for proposal generation and later evaluation, which keeps generation and review on the same data path.

### 2. Shared macro and industry context
The app stores broader reusable context by scope:
- macro
- industry
- ticker signal snapshots for per-run triage state

This lets multiple recommendations share the same broader context window and link back to the exact artifacts they used.

Industry scope is no longer only a ticker-to-industry label shortcut. The taxonomy layer now carries:
- per-ticker profiles
- explicit industry definitions
- sector definitions
- first-pass relationship edges such as `benefits_from`, `hurt_by`, and `sensitive_to`
- split ontology files so maintenance does not depend on one oversized JSON blob

That gives industry refresh and query generation a better base for broader coverage and clearer transmission framing.

Industry context snapshots now also persist matched ontology relationships in their metadata so operator-facing summaries and detail views can show which stored transmission edges were actually relevant to the current evidence.

Ticker deep analysis also derives ticker-level `peer_of`, `supplier_to`, and `customer_of` edges from the taxonomy profile. Those edges are stored in transmission diagnostics so trade review can show more than just abstract macro/industry pressure.

Watchlist orchestration now carries the matched ticker relationships into stored recommendation-plan transmission summaries. In practice that means plan review surfaces can show ticker-specific read-through like supplier dependence or peer confirmation without forcing the operator to open raw diagnostics first.

The same matched relationship set now feeds plan explanation text too. Rationale, action-reason detail, invalidation, and risk text can mention ticker relationship read-through, but only when the relationship was actually matched against the active evidence rather than just existing in the stored taxonomy.

Operator review surfaces now also have a dedicated relationship read-through presentation path. Instead of only seeing a compact helper-text line, the ticker page and run-detail plan review can show the matched relationships themselves, with stored-edge fallback when nothing matched strongly enough.

Under the hood, taxonomy themes and macro-sensitivity values are now normalized against governed registries. That is a step toward fully governed ontology values rather than letting those fields drift as scattered free-form strings.

Transmission channels are now on the same path. Ticker exposure channels, industry transmission channels, and relationship channels are normalized against a governed registry too, while operator-facing displays can still use readable labels derived from that controlled vocabulary.

The same cleanup now applies to ontology relationships themselves. Relationship types and target kinds are governed too, and the taxonomy service now derives extra structural edges such as `belongs_to_sector`, `linked_macro_channel`, and `exposed_to_theme`. That means downstream consumers can reason over a more explicit graph without having to duplicate that structure by hand in every other service.

Ticker deep analysis now pushes that governance a bit further downstream. Exposure-channel summaries now stay closer to actual transmission channels: synthetic keys used by the analysis are explicitly registered, channel-detail payloads carry readable labels, and raw theme / macro-sensitivity tags are no longer dumped into exposure-channel lists as if they were transmission channels.

The same cleanup now applies to summary semantics inside the transmission payload. Transmission tags, primary-driver keys, and conflict flags are governed too. Detailed event keys still exist, but they now live on dedicated fields like `macro_event_keys` and `industry_event_keys` instead of leaking into the governed summary-tag or driver lists.

If the relevant macro or industry artifact is missing or stale, the methodology falls back to neutral values and explicit warnings. Transitional support snapshots still support that shared-artifact layer and freshness reporting.

### 3. News ingestion and live ticker sentiment
`NewsIngestionService` fetches provider-backed articles, deduplicates them, normalizes them, and records feed usage and feed failures.

Ticker-level sentiment is then derived from the available articles.

Stored transparency fields include:
- `keyword_hits`
- `coverage_insights`
- feed errors
- source counts
- item counts

So a neutral score can mean either:
- the coverage was actually neutral
- or the coverage was weak

### 4. Optional summary enrichment
The app always stores a digest of the news context.

Operators can optionally route that digest and a compact technical snapshot through:
- `openai_api`
- `pi_agent`

The result is stored in `analysis_json.summary`. If summarization fails, the digest remains and the error is recorded.

## Feature engineering

The technical feature set includes market-derived inputs such as:
- trend indicators
- momentum indicators
- volatility measures
- reversion signals
- liquidity and volume context where available

The app persists both:
- raw values
- normalized values

## Scoring model

`weights.json` defines the relative influence of normalized features and aggregate signals.

At a high level, the scoring model:
- computes weighted contributions across the normalized feature vector
- builds aggregate directional context
- resolves a directional bias (`LONG`, `SHORT`, or `NEUTRAL`)
- computes a bounded confidence score

The app stores intermediate vectors, aggregations, and weights so operators can inspect what influenced the result.

## Price levels and risk

Entry, stop-loss, and take-profit are derived from the same technical and risk context as the rest of the recommendation.

In broad terms:
- entry starts from the current price context and may be adjusted by directional pressure
- stop-loss is based on volatility-sensitive distance
- take-profit is derived from the same risk budget with reward-side adjustments

## Outcome evaluation

The app stores `RecommendationPlanOutcome` records for evaluated plans.

Current evaluation records fields such as:
- entry touched
- stop-loss hit
- take-profit hit
- fixed-horizon returns (`1d`, `3d`, `5d`)
- maximum favorable excursion
- maximum adverse excursion
- realized holding period
- direction correctness
- confidence bucket
- setup family

These outcomes are written back into the main database and attached to plan reads as the latest stored outcome.

## Methodology limits

The current limits matter:
- recommendation quality still depends on external market and news inputs
- sentiment is inspectable, but not yet proven as a source of measured edge
- scheduler and workflow reliability still affect trust in the outputs
- cheap scan is only a triage layer, not the full trade-quality engine
- context extraction is still heuristic
- ticker deep analysis still reuses some older proposal internals
- confidence calibration needs more evidence over time

## See also

- `features-and-capabilities.md` — what the app can do now
- `raw-details-reference.md` — stored field and payload reference
- `roadmap.md` — what still needs work
- `archive/phase-2-app-native.md` — older phase history
