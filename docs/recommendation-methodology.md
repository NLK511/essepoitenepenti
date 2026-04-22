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
5. fetches recent OHLC data through a live-first hybrid path: fresh remote bars first in live runs, bounded retries on transient remote failures, then persisted local-bar fallback; replay stays point-in-time consistent
6. computes technical and context-enriched features with `pandas`
7. loads the latest shared macro and industry context snapshots through the context-native resolver layer
8. builds recommendation plans, diagnostics, and audit payloads
9. persists ticker signals, decision samples, recommendation plans when downstream plan framing actually ran, run summaries, and artifacts
10. emits explicit `no_action` plans when policy gates fail or evidence is too weak after shortlist/deep-analysis, while preserving cheap-scan-only rejections for non-shortlisted names as signal-plus-decision-sample audit records instead of full plans

`ProposalService` still exists as a lower-level helper for price history, feature engineering, news/context enrichment, and diagnostics, but it is no longer the main run-execution path.

## Persisted redesign objects

The current redesign path persists:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationDecisionSample`
- `RecommendationPlan` when the ticker actually reached downstream plan framing
- `RecommendationPlanOutcome`

Watchlist-backed jobs follow this staged flow:
1. scan
2. shortlist
3. deep analysis
4. calibration-aware confidence and policy gating
5. persistence of signals for all scanned names, decision samples for audit/tuning, and plans only for shortlisted names that actually entered plan framing

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
**Implementation status:**
- **implemented now:** live cheap-scan retry, live deep-analysis retry plus local fallback, replay-safe point-in-time behavior, and persisted fetch diagnostics in signal/plan/run detail payloads
- **still in progress:** better freshness scoring and richer operator-facing rendering of these diagnostics in the UI

The app uses a hybrid market-data strategy that balances freshness, resilience, and replay consistency.

**Cheap scan**
Cheap scan prefers local persistence first.
- **Preferred Source: Local Database** — it first attempts to fetch bars from the `historical_market_bars` table.
- **Timeframe Resolution:** it prefers `1m` bars and automatically resamples them to produce Daily OHLCV bars.
- **Fallback Timeframe:** if `1m` bars are missing, it falls back to `1d` bars stored in the database in replay mode.
- **Remote Fallback With Retry:** if local data is missing or insufficient, cheap scan retries transient remote fetch failures before giving up.
- **Failure Policy:** if remote fetch still fails but local data is sufficient, the ticker is scored from local data instead of being rejected for provider noise alone.
- **Lazy Hydration:** when a remote fetch succeeds, the system persists the retrieved bars back into the local database to accelerate future requests.
- **Cheap-scan thresholds:** the scan requires at least 30 bars in normal runs and at least 10 bars in replay runs. It emits the warning `cheap scan used limited lookback history` only when fewer than 50 bars were available, because that means the SMA50-style trend context had to use a shortened window.

**Deep analysis**
Deep analysis prefers freshness in live runs without making freshness a hard dependency.
- **Live Runs:** it tries fresh remote bars first, retries transient failures a bounded number of times, then falls back to persisted local `1d` bars if enough history exists.
- **Replay Runs:** it stays point-in-time consistent by preferring persisted bars and only using replay-bounded remote windows when needed.
- **Graceful Degradation:** fallback behavior is still recorded as degraded input rather than being treated as equal to a healthy remote fetch.
- **Failure Policy:** only after remote retry and local fallback both fail should deep analysis surface as unavailable.

**Where the fetch diagnostics are stored**
- **signal details:** `TickerSignalSnapshot.source_breakdown` and `TickerSignalSnapshot.diagnostics`
- **plan details:** `RecommendationPlan.signal_breakdown`
- **run/job details:** `Run.artifact_json.ticker_generation`
- **not included in summary rows:** these diagnostics should stay out of summary tables and compact list rows unless a later spec changes that

The same hybrid persistence layer is also reused by later evaluation logic.

Cheap-scan liquidity uses a simple `close * volume` notional measure over the last 20 bars. The operator-facing warning is therefore `low average traded value on cheap scan`, not "dollar volume", because the current implementation does not FX-normalize non-USD listings.

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
- relative-strength comparisons versus the broad market and the ticker's sector ETF
- simple volume-confirmation measures such as current volume versus its recent baseline

The app persists both raw and normalized values.

### Current implementation status
- **implemented now:** broad-market relative strength (`SPY`) and sector-ETF relative strength over short and medium lookbacks, plus simple volume-ratio and dollar-volume-ratio confirmation features in ticker deep analysis
- **implemented now:** if benchmark or sector ETF data is missing, deep analysis falls back to neutral values and records the gap in diagnostics instead of failing the whole recommendation
- **not implemented yet:** broader feature expansion such as full breadth, gap/overnight behavior, or more advanced chop/compression regime measures

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

Light feature wiring is now in place:
- aligned relative strength versus `SPY` and sector can modestly lift directional confidence
- stronger-than-normal volume participation can modestly lift technical and execution clarity
- these features are used as supporting evidence, not as dominant drivers yet

A data-quality cap can reduce the final confidence when warnings, weak coverage, or feed errors are present.

### Setup family
Each recommendation is classified into a setup family for later analysis and calibration, including:
- catalyst follow-through
- continuation
- breakout/breakdown
- mean reversion
- macro beneficiary/loser

Light feature wiring is also in place here:
- strong relative strength plus above-baseline volume can help confirm a continuation or breakout-style label
- when those confirming features are absent, the older momentum/RSI rules still remain the main path

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

To enable recall optimization, the evaluation pipeline actively tracks **phantom trades** for skipped setups that still retain executable framing. If a `no_action` or `watchlist` plan carries an intended direction plus valid entry, stop, and take-profit levels, the evaluator simulates it against live market data and records phantom outcomes such as `phantom_win`, `phantom_loss`, or `phantom_no_entry`. Cheap-scan-only rejected names that never received full trade framing do not get synthetic plan rows or phantom outcomes; they remain signal-plus-decision-sample audit evidence. This preserves quota savings from shortlist gating while still letting tuning engines learn from genuine near-miss setups that actually reached downstream framing.

If a trade plan is still unresolved after its generated horizon has elapsed, the evaluator resolves it as `expired` so stale plans do not remain indefinitely open.

`expired` is a terminal lifecycle outcome for audit and filtering purposes, but it is not treated as a `win` or `loss` by default.

## Decision samples for tuning

Every scanned ticker may produce a `RecommendationDecisionSample` row.

This is a tuning and review artifact, not a final outcome record.

Implementation status:
- **implemented now:** shortlisted names produce both plans and decision samples; cheap-scan-only rejected names still produce decision samples linked to their signal snapshot even when no plan row is created
- **important boundary:** non-shortlisted decision samples are meant to explain shortlist behavior, not to pretend downstream trade framing happened

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
