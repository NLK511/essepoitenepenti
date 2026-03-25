# Recommendation Methodology

This document explains how Trade Proposer App produces recommendations through its app-native scoring pipeline.

The goal of the methodology is not to maximize signal complexity. The goal is to generate recommendations that are reproducible, inspectable, and honest about degraded inputs.

Just as importantly, the methodology should currently be read as a structured decision-support and candidate-ranking process, not as a fully validated predictive engine. Stronger predictive claims should only follow once the redesign path has outcome tracking, confidence calibration, and evidence that recommendation quality is improving in measured terms.

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
3. deep analysis only for shortlisted names through `TickerDeepAnalysisService`
4. persistence of `TickerSignalSnapshot` and `RecommendationPlan` for every scanned ticker
5. creation of legacy `Recommendation` rows only for actionable deep-analysis outputs

Current limitation:
- manual ticker proposal jobs still use the legacy per-ticker production path
- `TickerDeepAnalysisService` now executes its own native deep-analysis flow for watchlist orchestration, but it still reuses some legacy proposal-service internals and payload shapes rather than a fully separated ticker engine
- macro and industry refresh runs now write context objects through news-first transitional writers, but those writers are still heuristic and not yet backed by a mature event pipeline
- the redesign path now has first-class recommendation outcome persistence/evaluation, but setup-family-aware generation and confidence calibration are still incomplete

## Recommendation-plan outcome evaluation

The redesign path now persists `recommendation_outcomes` for `RecommendationPlan` objects.

The current evaluation flow records measures such as:
- entry touched or not
- stop-loss hit or not
- take-profit hit or not
- fixed-horizon returns (`1d`, `3d`, `5d`)
- maximum favorable excursion
- maximum adverse excursion
- realized holding period
- direction correctness
- confidence bucket
- setup family

Those outcomes are written back into the main app database, surfaced through the API, and attached to recommendation-plan reads as the latest stored outcome so operators can review trade-plan quality without leaving the redesign workflow.

Current limitation:
- the app is now storing the right evaluation data, but it is not yet using that history to calibrate confidence or materially retrain setup logic
- setup family is persisted at evaluation time today, but generation-time setup classification is still incomplete and should become native to the ticker-analysis layer

## App-native independence

The current pipeline is intentionally self-contained: recommendation generation, evaluation, optimization, and shared sentiment reuse all run inside this repository instead of delegating core behavior to a prototype script. That makes the methodology easier to inspect, easier to test, and less likely to drift from the product's stored diagnostics.

## Data and sentiment layers

The methodology combines technical, context, and sentiment signals.

### 1. Market data
The pipeline uses `yfinance` to retrieve price history and volume. That history drives the technical indicators and is also reused by evaluation workflows, which helps keep proposal generation and later outcome review on the same data path.

### 2. Shared context and sentiment snapshots
The methodology now separates reusable broader context by scope:
- **macro sentiment/context**: shared and refreshed through dedicated workflows
- **industry sentiment/context**: shared and refreshed through dedicated workflows
- **ticker sentiment**: computed live during proposal generation

This design improves:
- efficiency, because macro and industry context do not need to be recomputed for every ticker
- consistency, because multiple recommendations in the same window can share the same broader context
- traceability, because the exact snapshot or context IDs used by a recommendation are stored and linked in the UI

Current redesign direction:
- macro and industry should become increasingly context-first and event-centric
- sentiment labels should remain secondary to "what matters now" and "why it matters"
- shared context should help explain transmission and exposure, not just polarity

If the relevant macro or industry snapshot is missing or stale, the methodology falls back to neutral values and explicit warnings.

### 3. News ingestion and live ticker sentiment
`NewsIngestionService` fetches provider-backed articles, deduplicates them, normalizes them into a unified structure, and records both feed usage and feed failures.

A lightweight sentiment analyzer then derives ticker-level sentiment signals from the available articles. It stores transparency fields such as:
- `keyword_hits`
- `coverage_insights`
- feed errors
- source counts and item counts

So a neutral score can be understood as either real neutrality or missing coverage.

The redesign direction here is not simply "more news." It is better evidence quality:
- official and primary releases should matter more than generic syndication
- trade and industry sources should matter more for industry context
- social evidence should confirm, accelerate, or contextualize rather than dominate macro/industry judgment
- headline-only evidence should remain explicitly marked as lower-resolution evidence

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

Current realism constraint:
- a coherent score is not the same thing as validated predictive edge
- confidence should not remain a monolithic black-box number forever
- the redesign should move toward setup-aware scoring and decomposed confidence such as context confidence, directional confidence, catalyst confidence, technical clarity, and execution clarity

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
- shared broader context is reusable and auditable
- degraded inputs become visible warnings
- evaluation can review outcomes against the original stored levels
- watchlist orchestration already explains shortlist and rejection behavior rather than hiding it in ranking internals

## Methodology limits

The methodology still has important limits:
- recommendation quality still depends on the quality and timeliness of external market/news inputs
- sentiment is inspectable, but not yet fully validated as a source of measurable edge
- scheduler and workflow reliability still matter because good methodology is less useful if operations are unreliable
- more signal sources should not be added faster than their effectiveness can be measured
- the redesign target architecture now has a real watchlist orchestration path, event-ranked news-first context writers, operator-visible shortlist reasoning, first-class recommendation-plan outcome tracking, and a dedicated ticker deep-analysis service boundary, but setup-family-aware generation, calibrated confidence, and deeper context extraction still need substantial work
- the app is not yet justified as a broad few-day swing predictor because setup-family performance and confidence calibration are still not first-class decision loops
- cheap scan is valuable for triage, but on its own it will not capture the full set of event-driven or regime-sensitive opportunities the redesign is supposed to surface

## Best next steps
Given the work already completed, the next best implementation steps are:
1. add explicit setup-family classification and setup-aware recommendation logic
2. use stored recommendation outcomes to calibrate confidence and compare setup-family performance
3. expose watchlist policy details more directly in operator workflows alongside the shortlist reasoning already surfaced
4. deepen `TickerDeepAnalysisService` into a fuller redesign-native ticker engine with less dependence on legacy proposal payload conventions
5. keep maturing macro/industry context extraction beyond the current heuristic event-ranking layer
6. only then decide how quickly to retire, absorb, or narrow the remaining sentiment-snapshot-first and legacy recommendation paths

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
