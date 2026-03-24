# Recommendation Methodology

This document explains how Trade Proposer App produces recommendations through its app-native scoring pipeline.

The goal of the methodology is not to maximize signal complexity. The goal is to generate recommendations that are reproducible, inspectable, and honest about degraded inputs.

## Methodology principles

The most important rule is the product-wide signal-integrity principle:
- missing or stale inputs should become explicit warnings or neutral values
- degraded sentiment or provider coverage should remain visible in diagnostics
- fallback behavior must not pretend to be equivalent to healthy input

That principle matters more than any individual indicator choice.

## Pipeline overview

### Current production pipeline
`ProposalService` orchestrates recommendation generation for one or more tickers in a run.

For each ticker, the current production pipeline:
1. fetches recent OHLC history through `yfinance`
2. computes technical indicators with `pandas`
3. builds raw and normalized feature vectors
4. loads the latest valid shared macro snapshot
5. loads the latest valid shared industry snapshot for the ticker's mapped industry
6. computes live ticker-specific sentiment from the current news payload
7. applies the configured weights from `src/trade_proposer_app/data/weights.json`
8. emits direction, confidence, entry, stop-loss, take-profit, and diagnostics
9. persists the full result and structured analysis payloads

If an input is unavailable, the system does not invent substitute confidence. It emits warnings or neutral values and stores why.

### Redesign path now partially implemented
The app now also has persisted redesign-domain objects for:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationPlan`

These exist as database models, repositories, migrations, read APIs, and run-detail/UI inspection surfaces.

In addition, watchlist-backed proposal jobs now use a real staged orchestration path:
1. cheap scan over all watchlist tickers
2. shortlist selection using the dedicated cheap-scan signal model
3. deep analysis only for shortlisted names
4. persistence of `TickerSignalSnapshot` and `RecommendationPlan` for every scanned ticker
5. creation of legacy `Recommendation` rows only for actionable deep-analysis outputs

Current limitation:
- manual ticker proposal jobs still use the legacy per-ticker production path
- deep analysis still depends on the legacy `ProposalService`
- macro and industry context writers are not yet the main saliency-first production path

## App-native independence

The current pipeline is intentionally self-contained: recommendation generation, evaluation, optimization, and shared sentiment reuse all run inside this repository instead of delegating core behavior to a prototype script. That makes the methodology easier to inspect, easier to test, and less likely to drift from the product's stored diagnostics.

## Data and sentiment layers

The methodology combines technical and sentiment context.

### 1. Market data
The pipeline uses `yfinance` to retrieve price history and volume. That history drives the technical indicators and is also reused by evaluation workflows, which helps keep proposal generation and later outcome review on the same data path.

### 2. Shared sentiment snapshots
The methodology now separates sentiment by scope:
- **macro sentiment**: shared and refreshed through dedicated snapshot workflows
- **industry sentiment**: shared and refreshed through dedicated snapshot workflows
- **ticker sentiment**: computed live during proposal generation

This design improves:
- efficiency, because macro and industry context do not need to be recomputed for every ticker
- consistency, because multiple recommendations in the same window can share the same broader context
- traceability, because the exact snapshot IDs used by a recommendation are stored and linked in the UI

If the relevant macro or industry snapshot is missing or stale, the methodology falls back to neutral values and explicit warnings.

### 3. News ingestion and live ticker sentiment
`NewsIngestionService` fetches provider-backed articles, deduplicates them, normalizes them into a unified structure, and records both feed usage and feed failures.

A lightweight sentiment analyzer then derives ticker-level sentiment signals from the available articles. It stores transparency fields such as:
- `keyword_hits`
- `coverage_insights`
- feed errors
- source counts and item counts

So a neutral score can be understood as either real neutrality or missing coverage.

### 4. Optional summary enrichment
The pipeline always stores a digest of the available news context. Operators can optionally route that digest and a compact technical snapshot through:
- `openai_api`
- `pi_agent`

The resulting narrative and metadata are stored in `analysis_json.summary`. If that path fails, the digest remains available and the error is recorded.

## Feature engineering

The technical feature set includes standard market-derived signals such as:
- trend indicators
- momentum indicators
- volatility measures
- reversion signals
- liquidity or volume context where available

The methodology persists both:
- raw values
- normalized values

This matters because the stored weights operate on normalized inputs, and audits need to show both the market observation and the transformed scoring input.

## Scoring model

`weights.json` defines the relative influence of the normalized features and aggregated signals.

At a high level, the scoring model:
- computes weighted contributions across the normalized feature vector
- builds aggregate directional context
- resolves a directional bias (`LONG`, `SHORT`, or `NEUTRAL`)
- computes a bounded confidence score

The methodology intentionally favors transparency over theoretical elegance: the app stores the intermediate vectors, aggregations, and weights so operators can inspect what influenced the result.

## Price levels and risk

Entry, stop-loss, and take-profit are derived from the same technical and risk context rather than being post-hoc decorations.

In general:
- entry starts from the current price context and may be nudged by directional pressure
- stop-loss is anchored to volatility-sensitive distance
- take-profit is derived from the same risk budget with reward-side adjustments

These values are persisted with the recommendation so later evaluation can judge the recommendation against the exact levels that were proposed.

## Diagnostics and stored payloads

Each recommendation and run persists structured artifacts such as:
- `analysis_json`
- `feature_vector_json`
- `normalized_feature_vector_json`
- `aggregations_json`
- `confidence_weights_json`
- warnings and provider errors
- timing metadata

`analysis_json` is the main operator-facing audit object. It records:
- recommendation metadata
- trade outputs
- summary metadata
- news coverage
- sentiment layers
- context flags
- feature vectors
- aggregations
- diagnostics

This is why the run detail and recommendation detail pages can explain what happened without relying on raw logs alone.

## Methodology strengths

The methodology is strongest where it is explicit:
- technical and sentiment signals are stored, not implied
- shared sentiment is reusable and auditable
- degraded inputs become visible warnings
- evaluation can review outcomes against the original stored levels

## Methodology limits

The methodology still has important limits:
- recommendation quality still depends on the quality and timeliness of external market/news inputs
- sentiment is inspectable, but not yet fully validated as a source of measurable edge
- scheduler and workflow reliability still matter because good methodology is less useful if operations are unreliable
- more signal sources should not be added faster than their effectiveness can be measured
- the redesign target architecture now has storage primitives, but not yet a full writer/orchestration pipeline

## Best next steps
Given the work already completed, the next best implementation steps are:
1. introduce real macro/industry context writers that populate the new context snapshot tables from saliency-first evidence
2. extract a dedicated ticker deep-analysis service so watchlist orchestration no longer depends on the legacy `ProposalService`
3. define and implement `RecommendationPlan` outcome tracking, evaluation, and backtesting
4. expose shortlist policy, thresholds, and reasons more directly in operator workflows rather than leaving them mostly in JSON payloads
5. only then decide how quickly to retire, absorb, or narrow the remaining sentiment-snapshot-first and legacy recommendation paths

## Practical reading guide

To inspect one recommendation end to end:
1. open the recommendation detail page for the trade object
2. open the source run for the execution context
3. inspect the shared snapshot references if present
4. inspect the structured diagnostics and sentiment coverage fields
5. compare later evaluation outcomes against the stored price levels

## Related docs
- `product-thesis.md`: goals, principles, and priority order
- `raw-details-reference.md`: field-level payload reference
- `features-and-capabilities.md`: current product behavior
- `phase-2-app-native.md`: self-contained pipeline progress and limits
