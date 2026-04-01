# Historical Replay and Backtesting Plan

**Status:** active implementation plan

## Why this exists

The app can already generate recommendation plans, persist context objects, and score outcomes over time.

What is still missing is a historical dataset rich enough to answer the most important product question:

> Do context-aware recommendation plans outperform simpler alternatives when evaluated on information that would have actually been available at the time?

Price history and technical indicators are straightforward to backfill.
The hard part is the app's differentiated layer:
- news
- social / tweet-like signals
- macro context
- industry context
- narrative summaries and event interpretation

This document defines the **target** path for historical replay: the practical and disciplined capability we want to build without pretending we can perfectly reconstruct every past state.

For current repo status, see the implementation snapshot below and `historical-replay-implementation-checklist.md`.

---

## Goals

### Primary goal

Build a historical replay system that can reconstruct, as faithfully as practical, the information available at time `T`, generate the app's intermediate objects and recommendation plans from that information, and evaluate those plans against subsequent outcomes.

### Secondary goals

- quantify whether context adds value beyond price/technical baselines
- measure calibration quality, not only raw returns
- identify which setup families, horizons, regimes, and context conditions actually work
- create a repeatable research workflow that uses the same conceptual objects as production
- establish a forward-compatible archival standard so future backtests improve over time

### Non-goals

This project does **not** aim to:
- perfectly reconstruct every historical tweet or deleted article
- claim exact reproduction of what the live app would have known on every historical timestamp
- optimize for maximum data quantity at the expense of point-in-time integrity
- introduce retrospective summaries that quietly leak future information into the replay

## Current implementation snapshot

This section separates what the repo already has from what this plan still expects.

### Already implemented
- Phase 1 replay batch/run scaffolding and API flow
- explicit replay provenance on generated batches and slices
- market-data hydration for replay inputs
- curated explicit universe presets
- `next_open` / `next_close` entry timing support in replay runs
- dummy replay signal scaffolding pending replacement with app-native signals

### Still expected
- stronger historical input coverage beyond market bars
- replay-generated context snapshots and plan outputs
- explicit outcome labeling and evaluation outputs for replay-generated plans
- archived provenance for future validation

The live recommendation-plan outcome resolution rules are **not** defined here. They live in `recommendation-plan-resolution-spec.md`.

---

## Driving uncompromisable principle

## Point-in-time integrity beats coverage.

If we must choose between:
- a smaller dataset that respects what was knowable at time `T`, and
- a larger dataset polluted by hindsight, revisions, survivorship, or future leakage,

we always choose the smaller dataset.

This principle is uncompromisable because a biased historical dataset would produce false confidence in the product and could easily overstate the value of the app's context layer.

### Practical implications

Every replayable object should be evaluated through this lens:
- **Was it available at or before the replay timestamp?**
- **Do we know when it first became available?**
- **Has it been revised, deleted, or reconstructed later?**
- **Are we labeling it as exact, approximate, or inferred?**

If the answer is unclear, the object must carry explicit provenance and confidence metadata, or it should be excluded from strict backtests.

---

## Core methodology

The system should replay a historical timestamp `T` as if the app were running then.

For each replay timestamp:
1. determine the tradable universe as of `T`
2. load price and volume history only up to `T`
3. compute technical indicators using only data available up to `T`
4. load historical news items first seen at or before `T`
5. load historical social items first seen at or before `T` when available
6. load macro events and macro state inputs known at or before `T`
7. derive support/context objects from those inputs
8. generate recommendation plans
9. compute future realized outcomes strictly after `T`
10. persist replay inputs, derived artifacts, and evaluation labels with provenance

The replay framework must be able to distinguish between:
- raw observable inputs
- derived features
- replay-generated interpretations
- realized future outcomes

---

## Data-quality tiers

Historical replay will necessarily mix sources with different fidelity. That is acceptable only if the tier is explicit.

### Tier A — point-in-time strong
Use when timestamps and availability are trustworthy.

Examples:
- OHLCV market data
- benchmark and sector ETF data
- earnings calendar / release timestamps
- economic release calendars
- filings and press releases with reliable publication time
- news metadata with trustworthy publish / first-seen timestamps

### Tier B — replayable approximation
Useful for research but not equivalent to perfect historical state.

Examples:
- archived article text from later-collected sources
- broad headline archives
- event datasets derived from historical news coverage
- partial social archives
- macro regime inputs reconstructed from market data and event calendars

### Tier C — inferred or synthetic
Useful for feature experiments, but should not be treated as strong production evidence.

Examples:
- LLM summaries generated today from archived historical inputs
- inferred context themes from later-assembled raw corpora
- social sentiment proxies when exact historical posts are incomplete

### Policy

All persisted replay artifacts should carry at least:
- `historical_source_tier`
- `available_at`
- `observed_at` or `published_at`
- `collected_from`
- `replay_version`
- `provenance_notes`
- `point_in_time_confidence`

---

## What we need to learn from backtesting

The historical replay system should answer these questions in order:

### 1. Does the plan framework work at all?
Compare against:
- buy-and-hold baselines
- sector ETF baselines
- simple technical strategies
- randomized or naive controls

### 2. Do technical filters improve plan quality?
Measure whether technical gating improves:
- hit rate
- expectancy
- drawdown control
- stop-out behavior
- time-to-target

### 3. Does context add incremental value?
Evaluate progressively:
- technical only
- technical + macro proxies
- technical + macro + industry
- technical + macro + industry + news
- technical + macro + industry + news + social

### 4. Is confidence calibrated?
Measure whether:
- higher-confidence plans produce better realized outcomes
- warning-heavy plans underperform cleaner plans
- setup-family and regime distinctions are meaningful

### 5. Which conditions are actually predictive?
Slice outcomes by:
- setup family
- horizon
- market regime
- transmission bias
- context regime
- macro stress vs benign environments
- industry participation and news intensity

---

## Required architecture direction

Historical replay should mirror production concepts instead of creating a separate research-only universe of objects.

### Preferred design principle

**Reuse live-domain objects where possible; add replay-specific provenance rather than parallel ad hoc schemas.**

That means historical research should revolve around familiar concepts such as:
- support snapshots or their eventual replacements
- macro context snapshots
- industry context snapshots
- ticker signals
- recommendation plans
- recommendation plan outcomes
- run summaries / artifacts

### Additional replay-specific needs

We will likely need dedicated storage for:
- historical raw inputs
- input availability timestamps
- replay configuration/versioning
- replay batch metadata
- evaluation labels by horizon
- provenance and confidence annotations

---

## Proposed phased plan

## Phase 0 — research framing and guardrails

### Objective
Define the rules, success criteria, and boundaries before building data pipelines.

### Deliverables
- finalized replay methodology and leakage rules
- list of accepted historical data sources by tier
- canonical definition of replay timestamp semantics
- evaluation metric set and baseline suite
- explicit policy for approximate vs strict backtests

### Key decisions
- replay granularity for the research MVP (daily vs intraday) as a replay-design choice, not a live plan-resolution rule
- entry timing convention, e.g. close-to-next-open or next-open execution
- outcome windows, e.g. 1d / 5d / 10d / 20d and excursion metrics
- whether news/social first-seen time or published time is authoritative when both exist

### Exit criteria
- no ambiguous use of future information remains in the MVP spec
- all MVP metrics and baselines are defined

---

## Phase 1 — market-data replay MVP

### Objective
Prove the replay engine on data that is easiest to trust.

### Scope
- OHLCV data
- benchmark data
- sector / industry mapping
- technical indicators
- universe membership logic as of `T` as far as practical
- future outcome labeling

### Deliverables
- replay runner that can iterate a historical date range
- market snapshot store or equivalent replay input layer
- technical feature generation constrained to data <= `T`
- outcome label generation
- baseline comparisons against simple strategies

### Questions answered
- can we generate historically valid plan candidates at scale?
- does the plan framing survive contact with future realized outcomes at all?

### Exit criteria
- successful end-to-end replay over a meaningful recent period
- baseline evaluation tables generated reproducibly

---

## Phase 2 — macro and industry proxy context

### Objective
Add context that is historically tractable even before full text/news/social coverage is complete.

### Scope
- macro event calendar
- rates / volatility / breadth / benchmark regime inputs
- sector and industry relative-strength data
- industry participation / breadth proxies
- macro and industry state features derived from market and calendar data

### Deliverables
- replayable macro proxy feature store
- replayable industry proxy feature store
- first historical macro context generation path
- first historical industry context generation path
- comparison of technical-only vs technical-plus-context-proxies performance

### Questions answered
- does context derived from observable market structure improve selection, calibration, or risk framing?

### Exit criteria
- macro and industry context replay artifacts persist with provenance
- incremental-lift comparisons are available

---

## Phase 3 — historical news ingestion and replay

### Objective
Introduce historical narrative/event inputs with reliable timestamps.

### Scope
- historical headlines
- article metadata
- article text where available
- ticker and industry mapping for articles
- first-seen / published timestamp handling
- event extraction from historical article content

### Deliverables
- historical news raw-ingest schema and loader
- replay-time news retrieval constrained by `available_at <= T`
- article relevance / mapping pipeline
- event extraction pipeline for historical content
- support/context snapshot generation with archived news as input

### Questions answered
- does news meaningfully improve context quality and plan outcomes?
- does article volume / source diversity / novelty add measurable lift?

### Exit criteria
- at least one robust news-backed replay period available
- context generation from historical news is reproducible and versioned

---

## Phase 4 — social and alternative sentiment inputs

### Objective
Add social data where realistically obtainable, without blocking the broader replay program.

### Scope
- historical social archives where licensing and access allow
- non-X social proxies if they are more feasible
- coverage-quality measurement by period and source
- clear fallback behavior when social inputs are missing

### Deliverables
- social replay ingestion path
- coverage diagnostics by ticker/date/source
- social-on vs social-off comparison framework
- provenance labels showing completeness confidence

### Policy
Social is additive, not foundational, for the historical replay MVP.
If coverage is partial, backtests must report that explicitly rather than quietly blending missingness into the signal.

### Exit criteria
- social coverage quality is measurable
- social incremental value can be evaluated only where coverage is acceptable

---

## Phase 5 — replay-generated context snapshots and plan generation parity

### Objective
Bring historical replay closer to live app behavior by generating the same core intermediate objects.

### Scope
- historical support/context snapshot creation from replay inputs
- ticker signal generation from replay-time inputs
- recommendation plan generation from replay-time inputs
- run-summary and artifact persistence for replay jobs

### Deliverables
- replay job type(s)
- replay-run artifact schema
- context snapshot generation with replay provenance
- ticker-signal and recommendation-plan generation in replay mode
- side-by-side comparison between live-path logic and replay-path logic

### Questions answered
- can research and production use the same conceptual pipeline?
- where does replay divergence from live execution still exist?

### Exit criteria
- historical replay produces first-class app-native objects, not only CSV outputs
- generated objects are reviewable in a structured way

---

## Phase 6 — evaluation, calibration, and operator-facing research outputs

### Objective
Turn raw replay runs into usable product evidence.

### Scope
- performance dashboards or exported reports
- confidence calibration studies
- setup-family comparisons
- regime / transmission / context slices
- robustness analysis by source tier and period

### Deliverables
- standard replay evaluation notebook/report pipeline
- calibration tables and plots
- slice-level outcome reports
- failure-mode catalog for poor plan classes
- recommendation on which setup families or contexts to keep, modify, or retire

### Exit criteria
- the team can answer which parts of the methodology are working and which are not
- historical evidence can inform production scoring changes responsibly

---

## Phase 7 — forward archival standard

### Objective
Make future backtesting stronger than past reconstruction.

### Scope
- archive raw external payloads as they are observed live
- persist first-seen timestamps and provider provenance
- persist model/prompt/version identifiers for generated summaries
- retain intermediate inputs needed to rebuild context decisions later

### Deliverables
- forward archival schema and retention policy
- provider payload capture hooks
- prompt/model version capture for generated context artifacts
- audit-friendly provenance across refresh, context, and proposal generation flows

### Exit criteria
- future periods become gold-standard backtest windows
- historical validation quality improves automatically over time

---

## Strict backtest vs research backtest

We should support two clearly named modes.

### Strict backtest
Use only high-confidence point-in-time inputs.

Purpose:
- production-quality evidence
- governance and trust
- claims about real-world robustness

### Research backtest
Allows approximate but labeled inputs.

Purpose:
- feature exploration
- directional signal research
- prioritization of future ingestion work

### Rule
Results from research backtests must never be presented as equivalent to strict backtests.

---

## MVP recommendation

The fastest useful MVP is:
- **research replay mode with daily granularity** for the initial backtesting slice
- free-provider daily OHLCV as a research-grade source
- explicit ticker-list universes only
- first curated presets: `us_large_cap_top20_v1` and `eu_large_cap_top20_v1`
- canonical entry timing: `next_open`, with `next_close` supported as a research fallback
- OHLCV + technical indicators
- macro event calendar and market-regime proxies
- industry relative-strength proxies
- a deliberately dummy placeholder signal rule for the first replay slice runner, documented as temporary and intended to be replaced by the app-native signal pipeline later
- historical headlines with timestamps and source
- optional article text when available
- no dependency on full tweet/X coverage

This MVP is about replay research throughput, not live recommendation-plan win/loss semantics. Live outcome resolution remains governed by `recommendation-plan-resolution-spec.md`.

This MVP is enough to test:
- whether context-aware plans beat technical-only baselines
- whether context improves calibration
- whether some setup families are robust and others should be pruned

---

## Risks and failure modes

### Leakage risk
Future information can enter through:
- revised articles
- day-end summaries used at market open
- features computed from post-`T` data
- retrospective LLM prompts

### Coverage bias
Archives may overrepresent:
- large-cap names
- currently surviving tickers
- major publications
- periods with better source coverage

### Social incompleteness
Historical social data may be partial, unstable, or non-licensable.
This should affect scope decisions, not invalidate the whole project.

### Replay drift
If live logic changes over time, replay results may become hard to compare across versions.
That is why replay configuration and methodology versioning are required.

---

## Recommended implementation order for this repo

1. define replay timestamp semantics and evaluation metrics
2. add replay batch / replay-run persistence and provenance fields
3. implement Phase 1 market-data replay
4. add macro and industry proxy context
5. add historical news ingestion and event extraction
6. add replay-generated context snapshots and plan outputs
7. add social inputs only where source quality justifies the effort
8. add operator/research reporting and calibration analysis
9. add forward archival capture so future validation is much stronger

---

## Success criteria

This project is successful when we can say, with evidence:
- which recommendation-plan setups have positive expectancy
- whether context adds measurable value over technical-only baselines
- whether confidence and warnings are directionally calibrated
- which contexts, industries, horizons, and regimes deserve continued investment
- which parts of the methodology should be simplified, retrained, or removed

The project is **not** successful if it merely produces a large historical dataset with unclear provenance and inflated results.

---

## Decision standard

When a design choice is unclear, prefer the option that:
1. preserves point-in-time integrity
2. makes provenance explicit
3. reuses production concepts
4. allows strict and approximate research modes to remain clearly separate
5. improves future archival quality, not only past reconstruction

## See also

- `historical-replay-implementation-checklist.md` — concrete codebase implementation order and module-level checklist
