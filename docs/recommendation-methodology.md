# Recommendation Methodology

**Status:** current behavior

Binding summary of how the app produces recommendation outputs. The current system is decision support and candidate ranking, not proven autonomous predictive skill.

## Core rule

Signal integrity wins:
- missing/stale inputs become warnings or neutral values
- degraded provider coverage stays visible
- fallback behavior is not presented as equal to healthy input
- outputs must be reproducible, inspectable, and explicit about degraded evidence

## Pipeline

The active proposal path is watchlist-oriented and coordinated by `WatchlistOrchestrationService`. `WatchlistExecutionService` owns run coordination; focused services handle shortlist selection, scan execution, signal building, plan framing/narrative, calibration review, transmission, and decision samples.

For each run:
1. resolve watchlist/manual ticker scope
2. run cheap scan across candidates
3. select shortlist with explicit rules
4. run `TickerDeepAnalysisService` for shortlisted names only
5. fetch OHLC data through live-first hybrid logic with retry/fallback; replay remains point-in-time consistent
6. compute technical/context features
7. load latest macro/industry context snapshots
8. build plans, diagnostics, narratives, calibration reviews, transmission summaries, and audit payloads
9. persist signals, decision samples, plans when plan framing ran, run summaries, and artifacts
10. emit explicit `no_action` plans only after shortlist/deep-analysis/policy gates; non-shortlisted names remain signal+decision-sample audit records, not full plans

`ProposalService` remains a lower-level helper for compatibility and shared feature/history/news/context work, not the main run executor.

## Persisted objects

Current redesign objects:
- `MacroContextSnapshot`
- `IndustryContextSnapshot`
- `TickerSignalSnapshot`
- `RecommendationDecisionSample`
- `RecommendationPlan` for tickers that reached downstream plan framing
- `RecommendationPlanOutcome`

Flow: scan → shortlist → deep analysis → calibration-aware confidence/policy gating → persist signals for scanned names, decision samples for audit/tuning, and plans only where plan framing ran.

## Research and tuning layers

- **Signal gating tuning:** upstream shortlist/threshold control
- **Plan-generation tuning:** downstream trade framing and actionable precision
- **Recommendation quality, calibration, baselines, evidence concentration, walk-forward:** trust and promotion review

Use signal gating when selection is too strict/loose, plan-generation tuning when trade framing is weak, and quality/walk-forward reports before trusting changes.

## Market data

Hybrid market data balances freshness, resilience, and replay consistency.

Cheap scan:
- prefers local `historical_market_bars`
- prefers `1m` bars resampled to daily OHLCV
- falls back to stored `1d` bars in replay
- retries transient remote failures
- scores from sufficient local data rather than rejecting for provider noise alone
- persists successful remote fetches
- requires at least 30 bars normally and 10 bars in replay
- warns `cheap scan used limited lookback history` only below 50 bars

Deep analysis:
- live runs try fresh remote bars, retry, then fall back to persisted local `1d` if sufficient
- replay uses point-in-time persisted or replay-bounded data
- fallback is recorded as degraded input
- unavailable only after retry and fallback fail

Fetch diagnostics live in signal details, plan signal breakdown, and run artifacts; they should stay out of compact summary rows unless re-specified.

Cheap-scan liquidity uses simple `close * volume` over 20 bars, so the warning is `low average traded value on cheap scan`, not FX-normalized dollar volume.

## Macro and industry context

Macro/industry context snapshots are canonical shared artifacts. Missing/stale artifacts fall back to neutral values and explicit warnings. Industry missing-snapshot handling is blocked rather than neutrally informative, and thin snapshots expose evidence/coverage states.

The taxonomy layer provides ticker profiles, industries/sectors, relationship edges, and governed labels so the app can expose readable transmission/read-through fields.

Context scores:
- **saliency:** prominence of active events/drivers
- **confidence:** trustworthiness given evidence, source quality, contradictions, degradation
- **quality:** usable/degraded/blocked after separating required vs optional evidence

These are review aids, not prediction probabilities. Industry context only adds positive support when usable evidence exists.

Current extraction is heuristic but preserves more short-horizon state than broad theme detection: persistence, transition, catalyst type, interpretation, trigger actor metadata, and why-now summary. Target context reads should include active driver, concrete catalyst, change vs prior snapshot, escalation/easing/stabilizing/mixed state, transmission mechanism, and explicit uncertainty.

## News, sentiment, and market intelligence

`NewsIngestionService` normalizes/deduplicates articles and records feed usage/failures. Preferred free sources are Google News RSS, Yahoo Finance, and Finnhub. NewsAPI is disabled by default on the free plan.

Ticker sentiment comes from the available article set. Neutral sentiment can mean neutral coverage or weak coverage; transparency fields include keyword hits, coverage insights, feed errors, source counts, and item counts.

Market intelligence is disabled by default unless explicitly configured. Disabled snapshots are absence markers only: zero confidence contribution and no active supporting/conflicting narrative. See `market-intelligence-analysis-spec.md`.

Optional digest summaries may use `openai_api`, `pi_agent`, or built-in `news_digest`; failures keep the fallback digest and record the error.

## Feature engineering

Features include trend, momentum, volatility, mean reversion, liquidity/volume, relative strength vs broad market/sector ETF, and volume confirmation. Raw and normalized values are persisted.

Current status:
- broad-market (`SPY`) and sector-ETF relative strength over short/medium lookbacks are implemented
- volume-ratio and notional-volume-ratio confirmation are implemented
- feature/context/normalization/aggregation logic lives in `TickerTechnicalFeatureService`
- payload/diagnostic construction lives in `TickerAnalysisPayloadService`
- `TickerDeepAnalysisService` coordinates native deep analysis and compatibility wrappers
- missing benchmark/sector ETF data falls back to neutral values with diagnostics
- broader features such as breadth, gap/overnight behavior, and chop/compression regimes remain future work

## Scoring and confidence

`weights.json` defines normalized feature/aggregate-signal influence.

Directional bias (`LONG`, `SHORT`, `NEUTRAL`) comes from trend, momentum, ticker/industry/macro alignment, and strong catalyst/news pressure. It must follow the combined directional score, not SMA200 alone. Material divergence remains visible and can block actionability.

Plan confidence aggregates:
- context confidence
- directional confidence
- catalyst confidence
- technical clarity
- execution clarity

Cheap-scan confidence is shortlist triage. After deep analysis, the recommendation-plan action gate uses deep-analysis confidence as raw plan confidence. If deep analysis is unavailable, it falls back to cheap-scan confidence and records degradation. Paper-account exploration may relax action gating to collect outcomes while preserving raw calibrated confidence.

Relative strength and volume confirmation can modestly support directional/technical/execution clarity, but they are not dominant drivers. Data-quality caps can reduce final confidence.

## Setup family

Plans are classified for behavior, evaluation, calibration, and explanation. Families include continuation, breakout, breakdown, mean reversion, catalyst follow-through, macro beneficiary/loser, and no-action/uncategorized states.

Family labels should change trade construction, invalidation, evaluation expectations, and operator explanation—not be cosmetic.

Guidance:
- continuation: pullback/reclaim entries and trend-extension targets
- breakout/breakdown: break/retest entries, failed-break stops, measured/next-level targets
- mean reversion: exhaustion/reversal confirmation, stops beyond extremes, midpoint/MA targets
- catalyst follow-through: fresh credible catalyst and confirmation; invalid if confirmation fades
- macro beneficiary/loser: explicit non-stale exposure channel and transmission-based invalidation

Family-specific `no_action` is valid when structure exists but confidence, execution quality, calibration, or invalidation clarity is insufficient.

## Transmission analysis

Transmission tracks how macro/industry context carries into a ticker. It should answer: active context, concrete catalyst/change, exposed industries/tickers, channels, supportive/hostile/mixed/negligible direction, and expected window.

Transmission is a governed edge graph, not a flat label match. Edges can carry direction, mechanism, confidence/provenance, validity window, and relationship score.

Ticker-facing summaries should preserve context bias, alignment, drivers, industry/ticker channels, expected window, catalyst intensity, conflicts, and decay state.

Scoring considers alignment, relevance, freshness, source quality, horizon fit, contradiction penalties, and edge strength. Severe direct conflicts can hard-block; timing/context-quality/mixed-context conflicts usually degrade and warn. Social-only polarity noise must not by itself raise contradiction flags.

Context quality gating is tiered: one weak layer usually degrades; broad broken backdrop or missing dominant evidence can block.

## Price levels and risk

Entry, stop-loss, and take-profit derive from the same technical/risk context as the recommendation:
- entry starts from current price context
- stop is volatility-sensitive
- take-profit follows risk budget with reward-side adjustments

Plan-generation tuning may adjust this framing through its registered active config.

## Outcome evaluation

`RecommendationPlanOutcome` records include entry touched, stop hit, target hit, fixed-horizon returns, favorable/adverse excursion, holding period, direction correctness, confidence bucket, setup family, transmission bias, and context-regime slices.

`watchlist` and `no_action` plans are first-class evaluated outcomes when they reached plan framing. If they retain intended direction and valid entry/stop/take-profit, the evaluator simulates phantom outcomes (`phantom_win`, `phantom_loss`, `phantom_no_entry`) against market data. Cheap-scan-only rejected names do not get synthetic plan rows or phantom outcomes.

Unresolved plans whose horizon elapsed resolve to `expired`. `expired` is terminal for lifecycle/filtering but not a win/loss by default.

Simulation-only diagnostics such as entry misses help tune setup/entry quality and are not broker-preferred realized P&L evidence.

## Decision samples

Every scanned ticker may create a `RecommendationDecisionSample` for tuning/review. It is not a final outcome.

Current behavior:
- shortlisted names produce plans and decision samples
- cheap-scan-only rejected names produce decision samples linked to signal snapshots without plan rows

Stored context includes action/decision type, shortlist status/rank, confidence/calibrated confidence/threshold/gap, setup family, transmission bias, context regime, compact snapshots, and review priority.

Research filters include shortlist state, setup family, transmission bias, context regime, and dates. Calibration reports expose reliability bins, Brier score, and expected calibration error.

## Calibration governance

Calibration must expose sparse evidence instead of hiding it behind precise thresholds. Broader cohorts dominate narrow slices unless sample size is adequate.

Approved slices: confidence bucket, setup family, horizon, transmission bias, context regime, and horizon+setup family.

Suggested minimum resolved counts before a slice materially influences gating:
- horizon `12`
- setup family `10`
- confidence bucket `10`
- transmission bias `10`
- context regime `10`
- horizon+setup family `8`

Calibration may raise/relax thresholds, flag review, and explain blocking. It must not auto-size positions, claim thin-sample probabilities, bypass conflicts, overrule broken structure, or treat sparse slices as statistically meaningful.

Operator payloads should show raw/calibrated confidence, threshold adjustment, slices, sample status, resolved count, win rate, and reasons.

## Limits

Current limits:
- external data quality constrains recommendations
- sentiment/context extraction remain heuristic
- cheap scan is only triage
- ticker deep analysis still uses compatibility internals in places
- calibration and policy evidence are active but still accumulating depth
- measured edge is not yet proven enough for unsupervised money-making claims

## See also

- `features-and-capabilities.md`
- `raw-details-reference.md`
- `recommendation-plan-resolution-spec.md`
- `decision-sample-tuning-guide.md`
- `signal-gating-tuning-guide.md`
- `market-intelligence-analysis-spec.md`
