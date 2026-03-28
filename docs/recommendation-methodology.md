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
`ProposalService` orchestrates recommendation generation for one or more tickers in a run.

For each ticker, the pipeline:
1. fetches recent OHLC price history through `yfinance`
2. computes technical indicators with `pandas`
3. builds raw and normalized feature vectors
4. loads the latest valid shared macro artifact
5. loads the latest valid shared industry artifact for the ticker’s mapped industry
6. computes live ticker sentiment from current news input
7. applies weights from `src/trade_proposer_app/data/weights.json`
8. emits direction, confidence, entry, stop-loss, take-profit, and diagnostics
9. persists structured outputs and audit payloads

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

## Data layers used by the methodology

### 1. Market data
The app uses `yfinance` for price history and volume.

That data is used both for proposal generation and later evaluation, which keeps generation and review on the same data path.

### 2. Shared macro and industry context
The app stores broader reusable context by scope:
- macro
- industry
- ticker

This lets multiple recommendations share the same broader context window and link back to the exact artifacts they used.

If the relevant macro or industry artifact is missing or stale, the methodology falls back to neutral values and explicit warnings.

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
