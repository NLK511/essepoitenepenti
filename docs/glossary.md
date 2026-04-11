# Glossary

**Status:** shared vocabulary reference

This glossary defines the main terms used across the app and docs.

For page-level usage, see `operator-page-field-guide.md`.
For payload structure, see `raw-details-reference.md`.

## Core workflow terms

### Signal
A per-ticker triage or directional output, usually a `TickerSignalSnapshot`.

### Plan
Short for `RecommendationPlan`, the app’s main trade-planning object.

### Outcome
Short for `RecommendationPlanOutcome`, the measured result recorded later.

### Expired plan
A plan whose intended horizon elapsed without a terminal win/loss resolution.

`expired` is terminal and operator-visible, but it is neutral for win-rate scoring by default.

### Canonical review path
The main operator review chain:
- `TickerSignalSnapshot` = candidate review
- `RecommendationPlan` = action review
- `RecommendationPlanOutcome` = later measured result

### Run
An execution record created when a job is queued or executed.

### Job
A saved workflow definition that can be run manually or by the scheduler.

### Watchlist
A reusable universe of tickers plus market metadata and review assumptions.

## Trade-decision terms

### Action
The final recommendation state on a plan.

Common values:
- `long`
- `short`
- `watchlist`
- `no_action`

### Direction
The directional lean of a signal, usually `long`, `short`, or neutral.

Direction is not the same as action.

### Actionable plan
A plan proposing a trade, usually `long` or `short`.

### Phantom trade
A simulated trade tracked by the system when it explicitly decides not to take action (`no_action`), but stores intended entry/stop/target levels anyway. This enables the tuning engines to learn if skipping the trade was a mistake (optimizing for recall).

### Phantom win / Phantom loss
The evaluated outcome of a phantom trade. If a `phantom_win` occurs, the system missed a profitable opportunity. If a `phantom_loss` occurs, the system correctly avoided a bad setup.

### Confidence
An evidence-weighted estimate of how trustworthy and actionable a signal or plan is.

Confidence is not a guarantee.

For macro and industry context snapshots, the confidence badge is an operator trust score rather than a prediction probability.

Operator reading bands:
- `0.0–39.9` = light
- `40.0–64.9` = moderate
- `65.0–84.9` = strong
- `85.0+` = dominant

### Calibration
The process of comparing confidence-like outputs against actual outcomes and adjusting trust, thresholds, or displayed confidence.

### Setup family
The pattern or archetype the plan belongs to, such as breakout, continuation, mean reversion, or catalyst follow-through.

### Thesis
The compact explanation of why the trade might work.

### Entry / stop / take profit
The proposed trade levels used to define execution and risk.

### Risk-reward ratio
The implied reward relative to defined downside.

### Invalidation
What would break the trade thesis.

## Ranking and shortlist terms

### Cheap scan
The first-pass low-cost scan across a watchlist.

### Deep analysis
The second-stage richer analysis applied to shortlisted names.

### Attention score
A triage score answering:
> how much operator attention should this ticker get right now?

### Shortlist
The reduced set of tickers chosen for deeper analysis.

### Shortlist rank
The ticker’s relative standing among shortlisted names.

### Selection lane
The path through which a ticker was promoted into deeper analysis.

### Catalyst lane
A shortlist lane intended to preserve strong event-driven names.

### Catalyst proxy score
A heuristic measure of how catalyst-driven a ticker currently appears.

## Context and transmission terms

### Context
Broader reusable information that helps explain ticker behavior.

Usually:
- macro context
- industry context
- their transmission into a ticker setup

### Macro context
Reusable broader market context.

### Industry context
Reusable sector or industry context.

### Snapshot
A stored reusable artifact representing market context or support state at a point in time.

### Support snapshot
A retired transitional shared artifact.

Context snapshots are now the active shared-context path.

### Freshness
Whether shared context is still recent enough to trust normally.

### Coverage
How much evidence was found for a context or sentiment object.

### Saliency
How prominent an event or driver appears relative to others.

For macro and industry context, saliency is a bounded prominence score on a `0.00–1.00` scale.

Operator reading bands:
- `0.00–0.39` = light
- `0.40–0.64` = moderate
- `0.65–0.84` = strong
- `0.85+` = dominant

### Transmission
How macro or industry context is believed to influence a ticker.

### Transmission bias
A directional contextual effect such as tailwind, headwind, or mixed.

### Tailwind
Broader context supports the setup.

### Headwind
Broader context works against the setup.

### Transmission alignment
How well broader context and ticker-specific setup fit together.

### Expected transmission window
The estimated time window during which context is expected to matter.

### Drivers / primary drivers
The main reasons the system believes a ticker or context object is being influenced.

## Diagnostics and reliability terms

### Warning
A structured indicator that something important was degraded, weak, stale, or incomplete.

### Degraded
A state where an important input is missing, stale, weak, or failed.

### Diagnostics
Structured warnings, failures, timing, and audit details stored with runs, plans, signals, and snapshots.

### Missing inputs
A structured record of expected data or evidence that was not available.

### Provider error
A structured failure from an external source or service.

### Preflight
A readiness check that verifies important dependencies and freshness conditions.

### Health
Operational status reported through endpoints and UI summaries.

## Data and scoring terms

### Analysis JSON
The main per-ticker structured diagnostic payload persisted by the pipeline.

### Feature engineering
The process of turning market and context inputs into structured features.

### Feature vector
The raw or normalized numeric inputs used for scoring.

### Aggregations
Intermediate derived scores such as trend, momentum, or volatility summaries.

### Weights
The numeric influence values used by the scoring pipeline.

### Signal gating tuning
The research workflow that adjusts upstream shortlist selection and threshold behavior to improve recall.

### Plan generation tuning
The research workflow that ranks backtested candidate plan-generation configs and can promote guarded winners for live entry, stop-loss, and take-profit construction.

### Scored outcomes
The subset of outcomes used in default win-rate calculations.

By default this means `win` and `loss`. It explicitly excludes `open`, `expired`, `no_action`, `watchlist`, and all `phantom_*` outcomes. Phantom outcomes are only scored within the tuning engines.

## Evaluation and research terms

### Outcome evaluation
The process of checking what happened after a plan was generated.

### Horizon
The intended holding or evaluation timeframe.

### Horizon return
Return measured after a fixed elapsed period such as 1 day, 3 days, or 5 days.

### Confidence bucket
A grouped confidence range used for calibration and evaluation review.

### Baseline comparison
A comparison between actual recommendation behavior and simpler alternative cohorts.

### Evidence concentration
A review concept showing where measured evidence is strongest or weakest.

### Recommendation decision sample
An advanced-review artifact used for tuning and deeper post-hoc analysis.

## System terms

### Scheduler
The process that checks active job schedules and enqueues due runs.

### Worker
The process that claims queued runs and executes them.

### Queued run
A run stored but not yet claimed by the worker.

### Overlap handling
Scheduler/worker behavior that avoids duplicate execution for the same schedule slot.

### Legacy path
Older behavior or data models kept for compatibility, not as the preferred workflow.

## Practical distinctions

### Signal vs plan vs outcome
- **Signal** = why a ticker got attention
- **Plan** = what trade, if any, the app proposed
- **Outcome** = what happened later

### Confidence vs calibration
- **Confidence** = current estimate on a signal or plan
- **Calibration** = evidence-based review of whether that confidence deserves trust

### Context vs sentiment
- **Sentiment** = polarity
- **Context** = what matters, why it matters, and how it may transmit into a ticker

## See also
- `operator-page-field-guide.md`
- `recommendation-methodology.md`
- `raw-details-reference.md`
- `features-and-capabilities.md`
