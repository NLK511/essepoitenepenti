# Recommendation Methodology

**Status:** canonical recommendation logic

This document answers one question:
> how does the app produce recommendation outputs?

It describes the live recommendation path.

The goal is not to maximize signal count. The goal is to produce outputs that are:
- reproducible
- inspectable
- explicit about degraded inputs

Today this should be read as a decision-support and candidate-ranking system, not proof of broad predictive skill.

## Core rule

The methodology follows one main rule: signal integrity.

That means:
- missing or stale inputs become warnings or neutral values
- degraded provider coverage stays visible in diagnostics
- fallback behavior is not presented as equal to healthy input

## Pipeline overview

`WatchlistOrchestrationService` is the active proposal-generation path.

For each proposal run, the system:
1. resolves the watchlist or manual ticker scope
2. runs a cheap scan across candidates
3. selects a shortlist using explicit rules
4. runs `TickerDeepAnalysisService` for shortlisted names only
5. fetches recent OHLC data through `yfinance`
6. computes technical and context-enriched features with `pandas`
7. loads the latest shared macro and industry context snapshots through the context-native resolver layer
8. builds recommendation plans, diagnostics, and audit payloads
9. persists ticker signals, recommendation plans, run summaries, and artifacts
10. emits explicit `no_action` plans when policy gates fail or evidence is too weak, while preserving cheap-scan-only rejections for non-shortlisted names

`ProposalService` still exists as a lower-level helper for price history, feature engineering, news/context enrichment, and diagnostics, but it is no longer the main run-execution path.

## Persisted redesign objects

The current redesign path persists:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`

Watchlist-backed jobs follow this staged flow:
1. scan
2. shortlist
3. deep analysis
4. calibration-aware confidence and policy gating
5. persistence of signals and plans

## How the research and tuning surfaces relate

The app now has multiple research surfaces, and they should be read as separate layers rather than one generic optimizer.

Current division of labor:
- **signal gating tuning** = upstream shortlist and threshold control
- **plan generation tuning** = downstream plan framing and actionable precision
- **recommendation-quality summary, calibration, baseline comparisons, evidence concentration, and walk-forward validation** = trust and promotion review

In practical terms:
- if too many candidates are rejected too early or too much noise is entering deep analysis, inspect **signal gating tuning**
- if candidates are reaching plan generation but the trade framing is weak, inspect **plan generation tuning**
- if a change looks promising, use the **recommendation-quality and walk-forward surfaces** to decide whether it is actually credible on later data

## Data layers used by the methodology

### Market data
The app uses `yfinance` for price history and volume.

The same price-data path is used for both generation and later evaluation.

### Shared macro and industry context
The app stores reusable macro and industry context and links recommendations back to the artifacts they used.

The taxonomy layer now provides:
- ticker profiles
- industry and sector definitions
- relationship edges
- governed vocabularies for themes, channels, and related labels

That allows the system to:
- build industry refreshes from richer definitions
- surface ticker relationship read-throughs such as peers, suppliers, and customers
- keep operator-facing transmission labels readable without relying on raw internal keys

Macro and industry context now use context snapshots as the canonical shared-artifact layer for refresh, review, and proposal-time reuse.

If macro or industry artifacts are missing or stale, the methodology falls back to neutral values and explicit warnings.

Macro and industry context snapshots also carry two operator-facing heuristic scores:
- **saliency**: how prominent the active events or drivers look relative to the rest of the current evidence set
- **confidence**: how trustworthy the context read looks given evidence volume, source quality, contradictions, and degradation

These are bounded review aids, not prediction probabilities.

A current limitation is that context extraction is still not a fully mature event model, but it now does more than broad theme detection. Current macro and industry snapshots try to preserve short-horizon state through fields such as persistence state, state transition, catalyst type, market interpretation, trigger actor metadata, and a short why-now summary. That means the system is better than before at distinguishing cases like escalation versus de-escalation or guidance improvement versus guidance cuts, even though it still relies on heuristic extraction and imperfect evidence coverage.

So the intended target state for context is not just "theme detected". It is:
- the active theme or driver
- the concrete catalyst behind the latest move
- what changed versus the prior snapshot
- whether the state is escalating, easing, stabilizing, or mixed
- the main transmission mechanism into industries or tickers
- explicit uncertainty when evidence conflicts

Prompt quality matters here, but prompt wording alone is not enough. Better context quality also depends on better event definitions, more specific evidence triage, structured state fields that preserve short-horizon dynamics instead of compressing them away, and query generation that pulls more concrete industry evidence from ontology context.

### News ingestion and ticker sentiment
`NewsIngestionService` pulls and normalizes articles, deduplicates them, and records feed usage and failures.

The app currently prefers near-real-time free sources first, especially:
- Google News RSS
- Yahoo Finance
- Finnhub

NewsAPI remains disabled by default on the free plan.

Ticker sentiment is derived from the available article set.

Stored transparency fields include things like:
- keyword hits
- coverage insights
- feed errors
- source counts
- item counts

So a neutral score can mean either neutral coverage or weak coverage.

### Optional summary enrichment
The app stores digest-style summaries for news and context.

Operators can optionally route that digest through:
- `openai_api`
- `pi_agent`
- the built-in `news_digest` fallback

The result is stored in `analysis_json.summary`. If enrichment fails, the fallback digest remains and the error is recorded.

## Feature engineering

The feature set includes market-derived inputs such as:
- trend
- momentum
- volatility
- mean-reversion signals
- liquidity and volume context

The app persists both raw and normalized values.

## Scoring and confidence

`weights.json` defines the relative influence of normalized features and aggregate signals.

### Directional bias
The system resolves a directional bias (`LONG`, `SHORT`, or `NEUTRAL`) from:
- trend context such as price vs SMA200
- momentum across multiple lookback windows
- ticker, industry, and macro alignment

### Confidence
Confidence is a weighted aggregation of normalized components:
- **context confidence**
- **directional confidence**
- **catalyst confidence**
- **technical clarity**
- **execution clarity**

A data-quality cap can reduce the final confidence when warnings, weak coverage, or feed errors are present.

### Setup family
Each recommendation is classified into a setup family for later analysis and calibration, including:
- catalyst follow-through
- continuation
- breakout/breakdown
- mean reversion
- macro beneficiary/loser

### Transmission analysis
The methodology also tracks how well a trade idea is supported from macro or industry context down to the ticker.

In broad terms it considers:
- alignment across macro, industry, and ticker evidence
- relevance of matched themes or events
- freshness of supporting context
- contradiction penalties when major signals conflict

The app stores intermediate vectors, aggregations, and weights so operators can inspect what influenced the result.

## Price levels and risk

Entry, stop-loss, and take-profit are derived from the same technical and risk context as the rest of the recommendation.

In broad terms:
- entry starts from current price context
- stop-loss is volatility-sensitive
- take-profit is derived from the same risk budget with reward-side adjustments

## Outcome evaluation

The app stores `RecommendationPlanOutcome` records for evaluated plans.

Current evaluation records include fields such as:
- entry touched
- stop-loss hit
- take-profit hit
- fixed-horizon returns (`1d`, `3d`, `5d`)
- maximum favorable and adverse excursion
- realized holding period
- direction correctness
- confidence bucket
- setup family
- transmission-bias and context-regime slices used by downstream calibration summaries

`watchlist` and `no_action` plans are also preserved as first-class evaluated outcomes. 

To enable recall optimization, the evaluation pipeline actively tracks **phantom trades** for skipped setups that still retain executable framing. If a `no_action` or `watchlist` plan carries an intended direction plus valid entry, stop, and take-profit levels, the evaluator simulates it against live market data and records phantom outcomes such as `phantom_win`, `phantom_loss`, or `phantom_no_entry`. Cheap-scan-only rejected names that never received full trade framing remain ordinary non-trade outcomes. This preserves quota savings from shortlist gating while still letting tuning engines learn from near-miss setups.

If a trade plan is still unresolved after its generated horizon has elapsed, the evaluator resolves it as `expired` so stale plans do not remain indefinitely open.

`expired` is a terminal lifecycle outcome for audit and filtering purposes, but it is not treated as a `win` or `loss` by default.

## Decision samples for tuning

Every generated plan also produces a `RecommendationDecisionSample` row.

This is a tuning and review artifact, not a final outcome record.

It stores decision context such as:
- action and decision type
- shortlist status and rank
- confidence, calibrated confidence, threshold, and gap
- setup family, transmission bias, and context regime
- compact decision, signal, and evidence snapshots
- `review_priority` for borderline cases

The research workflow now exposes richer filters for these samples, including shortlist state, setup family, transmission bias, context regime, and date ranges. The calibration report endpoint also surfaces confidence reliability bins with Brier score and expected calibration error so operators can compare predicted confidence against realized outcomes.

See:
- `decision-sample-tuning-guide.md`
- `signal-gating-tuning-guide.md`

## Methodology limits

Current limits still matter:
- recommendation quality depends on external market and news inputs
- sentiment is inspectable, but not yet proven as measured edge
- cheap scan is only a triage layer
- context extraction is still heuristic
- ticker deep analysis still reuses some older proposal internals
- the shared context layer is context-native now, but its event extraction and scoring are still heuristic
- calibration is active, but evidence depth is still growing

Related references:
- `recommendation-plan-resolution-spec.md`
- `archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md`

## See also

- `features-and-capabilities.md` — what the app can do now
- `raw-details-reference.md` — stored field and payload reference
- `roadmap.md` — what still needs work
- `archive/phase-2-app-native.md` — older phase history
