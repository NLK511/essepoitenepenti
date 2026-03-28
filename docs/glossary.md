# Glossary

**Status:** shared vocabulary reference

This glossary defines the main product, workflow, and field terms used across Trade Proposer App.

It is meant to help operators read the UI and docs consistently. Definitions here are kept practical and product-specific.

For page-by-page usage guidance, see `operator-page-field-guide.md`.
For payload-level storage details, see `raw-details-reference.md`.
For recommendation logic, see `recommendation-methodology.md`.

---

## A

### Action
The final recommendation state on a `RecommendationPlan`.

Common values:
- `long`
- `short`
- `watchlist`
- `no_action`

Action is more important than raw directional bias because the app is allowed to identify a directional lean without forcing a trade.

### Actionable plan
A plan that is actually proposing a trade, usually `long` or `short`, rather than `watchlist` or `no_action`.

### Aggregations
Intermediate derived scores computed from lower-level features, such as momentum, trend, or volatility summaries. These help explain how raw inputs became directional or risk signals.

### Analysis JSON
The main structured per-ticker diagnostic payload persisted by the app-native pipeline. It stores trade outputs, sentiment layers, summary metadata, feature vectors, diagnostics, and related audit information.

### Attention score
A triage-oriented score used mainly on `TickerSignalSnapshot` objects.

It answers:
> how much operator attention should this ticker get right now?

Attention is not the same as confidence and not the same as actionability.

---

## B

### Baseline comparison
A comparison between actual recommendation-plan behavior and simpler alternative cohorts, such as high-confidence-only or cheap-scan-leader cohorts. Used to test whether complexity is adding value.

### Bias
A directional push or drag implied by signals or broader context.

Examples:
- bullish bias
- bearish bias
- transmission bias

### Breakout
A setup family where price is attempting to move through an important level with enough strength to support continuation.

---

## C

### Calibration
The process of comparing confidence-like outputs against actual outcomes and adjusting trust, thresholds, or displayed confidence accordingly.

In this app, calibration is meant to be operator-visible and sample-aware.

### Calibration review
Stored or computed information explaining how confidence was assessed against historical cohorts.

Common fields include:
- raw confidence
- calibrated confidence
- confidence adjustment
- effective threshold
- sample status
- cohort reasons

### Candidate ranking
The process of ordering tickers by how likely they are to be worth deeper review. In the current product, this is most visible in cheap scan, shortlist ranking, and attention-based triage.

### Canonical operator truth path
The main review chain the product wants operators to follow:
- `TickerSignalSnapshot`
- `RecommendationPlan`
- `RecommendationPlanOutcome`

This is preferred over legacy recommendation-history concepts.

### Catalyst
A development that could plausibly cause a short-horizon price move.

Examples:
- earnings-related read-through
- sector news
- macro event transmission
- company-specific developments

### Catalyst lane
A reserved shortlist path meant to promote names with notable event or catalyst evidence, so they are not crowded out entirely by technical ranking.

### Catalyst proxy score
A heuristic measure of how event- or catalyst-driven a ticker currently appears.

### Cheap scan
The low-cost first pass over a watchlist. It is used to screen many names quickly before deep analysis is applied to a smaller shortlist.

### Confidence
A bounded estimate of how trustworthy and actionable a plan or signal is, given available evidence, setup quality, and context quality.

Confidence is not a guarantee of success.

### Confidence adjustment
An upward or downward modification to raw confidence, usually based on calibration evidence, sample quality, or other governance logic.

### Confidence bucket
A grouped confidence range used for evaluation and calibration review.

### Context
Broader reusable information that helps explain or influence ticker behavior.

In this app, context usually refers to:
- macro context
- industry context
- their transmission into a ticker setup

### Context-first
A redesign principle where the system tries to identify what matters in the market and why, rather than relying only on sentiment labels.

### Context object
A persisted redesign-native broader-market artifact, such as a `MacroContextSnapshot` or `IndustryContextSnapshot`.

### Context regime
A label or grouping describing the broader market environment relevant to evaluation and calibration.

### Coverage
A summary of how much evidence was found for a sentiment or context object.

Coverage fields help distinguish true neutrality from missing or sparse evidence.

---

## D

### Dashboard
The main workspace overview page. Best used for first-pass triage.

### Deep analysis
The richer second-stage analysis applied only to shortlisted tickers after cheap scan.

### Degraded
A state where some required or important input is missing, stale, weak, or failed.

The product’s docs are explicit that degraded states should remain visible.

### Diagnostics
Structured warnings, problems, provider failures, timing, and related audit information stored with runs, signals, plans, and snapshots.

### Direction
The directional lean of a signal, usually `long`, `short`, or neutral.

Direction is not the same as action.

### Drivers
The main reasons behind a context snapshot, plan, or signal. Drivers should explain what the system thinks matters most.

---

## E

### Entry
The proposed price or entry zone where a trade would ideally be initiated.

### Entry style
A descriptive field explaining how the app wants the operator to think about the entry.

### Evidence concentration
A review concept showing where measured evidence is strongest or weakest. Used to decide whether the app should remain selective or is ready to broaden usage.

### Evidence summary
A structured plan-level summary of why a recommendation was promoted, blocked, or framed the way it was.

### Execution path
The workflow/orchestration path used by a run.

### Execution quality
How credible and tradeable the plan mechanics are, including entry, stop, target, and structure clarity.

### Expected transmission window
The estimated time window during which broader context is expected to influence the ticker.

---

## F

### Feature engineering
The process of turning market and context inputs into structured raw and normalized features used by the scoring logic.

### Feature vector
The set of raw or normalized numeric inputs used to score a ticker.

### Freshness
Whether a shared snapshot or context object is still recent enough to trust normally.

### Fused sentiment
A combined sentiment view built from multiple sentiment layers rather than one source alone.

---

## G

### Governance
The rules constraining how the system should use evidence, calibration, and degraded inputs.

### Green / healthy / ok
A general sign that a component, run, or check is not currently degraded in a meaningful way.

---

## H

### Health
Operational state reported through endpoints and UI summaries.

### Horizon
The intended holding or evaluation timeframe.

Common values include:
- `1d`
- `1w`
- `1m`

### Horizon return
Return measured after a fixed elapsed period such as 1 day, 3 days, or 5 days.

---

## I

### Industry context
Reusable broader context for a sector or industry, combining macro spillover with industry-native developments.

### Industry snapshot
A shared stored artifact representing the latest industry sentiment/context state for a given subject.

### Invalidation
The condition or reasoning that would make the trade thesis no longer credible.

### Invalidation summary
A short explanation of what would break the setup logic.

---

## J

### Job
A saved workflow definition that can be run manually or by the scheduler.

Common job types:
- proposal generation
- recommendation evaluation
- weight optimization
- macro sentiment refresh
- industry sentiment refresh

---

## L

### Lane
A shortlist pathway used to promote a ticker.

Examples:
- core technical lane
- catalyst/event lane

### Legacy path
Older data models or behavior kept only for historical or compatibility reasons, not as the preferred active workflow.

### LLM summary
A narrative summary produced by a configured summary backend, such as OpenAI or `pi_agent`.

---

## M

### Macro context
Reusable broader market context intended to capture important market-moving developments.

### Macro snapshot
A shared stored artifact representing the latest macro sentiment/context state.

### Manual tickers
A directly specified ticker list used by a proposal job instead of a watchlist.

### Mean reversion
A setup family based on the idea that price may revert back toward a recent average or equilibrium area.

### Missing inputs
Structured record of what data or evidence the system expected but did not receive.

### Mode
Signal-processing stage indicator, often used on ticker signals.

Common values:
- cheap scan
- deep analysis

---

## N

### Neutral
A non-directional or low-conviction output.

In this app, neutral values are often intentionally used when evidence is missing or genuinely balanced.

### No action
A valid successful recommendation state meaning the app does not believe a credible trade should be forced right now.

### Normalized feature vector
The transformed numeric feature set used directly by weight-based scoring.

### Nitter
A social-source integration used mainly as supporting evidence for macro and industry context, and optionally for ticker sentiment.

---

## O

### Operator
The intended user of the app: a trader or workflow owner reviewing and managing trade-planning outputs.

### Outcome
A measured result recorded after evaluating a recommendation plan.

### Outcome evaluation
The process of checking what happened after a plan was generated, using metrics such as stop hit, target hit, fixed-horizon returns, and excursion statistics.

### Overlap handling
Scheduler/worker behavior that avoids duplicate or conflicting execution for the same schedule slot.

---

## P

### Plan
Short for `RecommendationPlan`, the app’s canonical trade-planning object.

### Plan outcome
Short for `RecommendationPlanOutcome`, the canonical measured-result object attached to a plan.

### Preflight
A readiness check that verifies important dependencies and freshness conditions before normal operation.

### Primary drivers
The key reasons the app believes a ticker or context object is being influenced in a certain way.

### Proposal generation
The workflow that scans tickers and creates redesign-native signal and plan outputs.

### Provider error
A structured record of failure from an external source or service.

---

## Q

### Queued run
A run that has been created and stored but not yet claimed by the worker.

---

## R

### Recommendation plan
The redesign-native trade object storing action, confidence, entry, stop, target, thesis, warnings, and related evidence.

### Recommendation-plan outcome
The redesign-native evaluation object storing what happened after a plan was produced.

### Refresh
A workflow that recomputes shared context or sentiment snapshots.

### Risk-reward ratio
The implied reward relative to defined downside, based on target and stop placement.

### Run
An execution record created when a job is queued or executed.

### Run debugger
A quick-triage page for recent runs.

### Run detail
The full execution-review page for a specific run.

---

## S

### Saliency-first
A design principle where the app tries to identify what developments matter most rather than only scoring broad positive/negative sentiment.

### Schedule slot
A specific scheduled execution time used to prevent duplicate enqueues.

### Scheduler
The process that checks active job schedules and enqueues due runs.

### Scope
The level at which a signal or snapshot applies.

Common scopes:
- macro
- industry
- ticker

### Selection lane
The lane through which a ticker was promoted into deeper analysis.

### Sentiment
A polarity-oriented reading of evidence, usually on a negative-to-positive scale.

### Sentiment volatility
A rough measure of how unstable, mixed, or noisy sentiment appears.

### Setup family
A classification for the kind of trade setup the ticker appears to have.

Examples:
- breakout
- continuation
- mean_reversion
- breakdown
- catalyst_follow_through

### Shortlist
The reduced set of tickers chosen after cheap scan for deeper analysis.

### Shortlist reasoning
Operator-visible explanation of why a ticker was promoted, ranked, or rejected.

### Shortlist rank
The relative position of a ticker among shortlisted names.

### Signal
A structured directional or triage-oriented per-ticker output. In the redesign workflow, this is usually represented by `TickerSignalSnapshot`.

### Signal integrity
The core product rule that missing, stale, or degraded inputs must remain visible instead of being hidden by cosmetic fallback behavior.

### Signal breakdown
A structured plan-level explanation of how component signals and context contributed to the final plan.

### Snapshot
A stored reusable artifact representing market context or sentiment at a particular time.

### Source breakdown
A structured summary of which sources contributed to an output and in what proportions or counts.

### Summary backend
The configured mechanism used for narrative summarization.

Common backends:
- `news_digest`
- `openai_api`
- `pi_agent`

### Summary prompt
The operator-configurable prompt used when the summary backend relies on an LLM.

### Synthetic wrapper
A redesign compatibility mechanism used to route manual ticker jobs through the newer orchestration model.

---

## T

### Tailwind
A positive transmission bias where broader context supports the setup.

### Technical setup
The chart- and market-structure side of the trade idea.

### Thesis
The compact explanation of why the trade might work.

### Ticker drill-down
The page focused on one ticker’s plan history, outcomes, and reference trade history.

### Ticker signal snapshot
The redesign-native stored per-ticker signal object that captures triage, directional, and shortlist-related information.

### Timing expectation
The app’s expectation for when the setup should matter most.

### Transmission
The mechanism by which macro or industry context is believed to influence a specific ticker.

### Transmission alignment
A measure of how well broader context and ticker-specific setup fit together.

### Transmission bias
A directional classification of contextual effect, such as tailwind or headwind.

### Transmission contradiction
A state where broader context contains enough conflicting evidence that the app may reduce confidence or block action.

### Transmission tags
Compact labels describing relevant contextual transmission characteristics.

### Trend score
A cheap-scan or signal component describing the strength and quality of trend structure.

---

## U

### Uncertainty
A legitimate outcome in this product. The system is allowed to be uncertain and should prefer visible uncertainty over false confidence.

---

## W

### Warning
A structured indicator that something important was degraded, weak, stale, or incomplete.

### Watchlist
A reusable universe of tickers plus market metadata and review assumptions.

### Watchlist plan
A non-trade action state meaning a ticker should be monitored but is not a trade yet.

### Weight optimization
The workflow that adjusts scoring weights using stored recommendation-plan outcomes.

### Weights
The numeric influence values used by the scoring pipeline. Stored in `src/trade_proposer_app/data/weights.json`.

### Worker
The process that claims queued runs and executes them.

### Workflow
A type of job/run behavior, such as proposal generation or evaluation.

---

## Practical reading tips

### If you are confused between signal, plan, and outcome
Use this chain:
- **Signal** = why a ticker got attention
- **Plan** = what trade, if any, the app proposed
- **Outcome** = what happened later

### If you are confused between confidence and calibration
Use this distinction:
- **Confidence** = current estimate attached to a signal or plan
- **Calibration** = evidence-based review of whether confidence deserves trust

### If you are confused between context and sentiment
Use this distinction:
- **Sentiment** = polarity
- **Context** = what matters, why it matters, and how it may transmit into a ticker

---

## See also
- `operator-page-field-guide.md` — where the terms show up in the UI
- `recommendation-methodology.md` — how the pipeline uses many of these terms
- `raw-details-reference.md` — field and payload reference
- `features-and-capabilities.md` — current product behavior
