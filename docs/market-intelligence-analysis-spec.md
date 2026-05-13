# Market intelligence analysis spec

**Status:** current + target behavior

## Problem

The analysis stack already uses:
- market price history
- technical features
- news and social context
- macro and industry context
- transmission and calibration heuristics

But it still misses three high-value short-horizon inputs:
- event calendar / corporate catalysts
- options context / options flow pressure
- analyst revisions and rating changes

Without those inputs, the system often has enough evidence to produce a plan, but not enough structured evidence to justify higher confidence. That contributes to many plans clustering below the 70% range.

## Current behavior

The current analysis path already supports:
- ticker technical features
- news-backed context
- macro and industry snapshots
- transmission analysis
- calibration review
- diagnostic warnings and fallback behavior when inputs are missing

What it does **not** yet have is a dedicated market-intelligence layer for:
- scheduled events
- event-driven catalyst timing
- options pressure / implied-volatility context
- analyst sentiment and estimate/revision context

So today those signals are either absent or only weakly implied by news/context.

## Target behavior

Add a canonical **market intelligence** layer that becomes part of ticker analysis and plan framing.

It should answer four questions:
1. **What event is active or imminent?**
2. **What does the options market imply about expectation, pressure, and risk?**
3. **What do analysts now imply about direction or valuation?**
4. **Does this materially strengthen or weaken the trade idea already suggested by price/news/context?**

This layer must be evidence-aware, replay-safe, and conservative. It should improve confidence only when the new data aligns with the existing setup; it should reduce confidence or emit warnings when it conflicts.

## Non-goals

- Not a replacement for technical analysis.
- Not a standalone prediction engine.
- Not a requirement to add expensive premium vendors first.
- Not a license to treat true options flow as equivalent to options chain data.

## Canonical design

Use one canonical analysis layer named **market intelligence**, with three subdomains:
- **event intelligence**
- **options intelligence**
- **analyst intelligence**

Each subdomain should be normalized into a comparable internal shape before scoring.

### Canonical snapshot fields

A ticker/as-of market-intelligence snapshot should minimally expose:
- `ticker`
- `as_of`
- `source_set`
- `coverage_status`
- `freshness_status`
- `event_intelligence`
- `options_intelligence`
- `analyst_intelligence`
- `confidence_contribution`
- `conflict_flags`
- `warnings`
- `provider_diagnostics`
- `raw_payload_refs`

### Subdomain fields

#### Event intelligence
Should capture:
- earnings date and release timing
- guidance / investor day / product event / conference event
- split / dividend / merger / FDA / court / SEC filing / other catalyst class
- event imminence window
- whether the event is already past, pending, or stale
- expected transmission window
- event saliency / catalyst strength

#### Options intelligence
Should capture:
- chain coverage availability
- implied volatility / IV rank / IV change
- open interest changes
- unusual volume / contract concentration
- call-put skew / pressure
- put-call ratio style pressure
- liquidity quality / spread quality
- expiry alignment with the thesis window
- true flow fields when available (sweeps, blocks, repeated prints)

#### Analyst intelligence
Should capture:
- rating changes
- price-target changes
- estimate revisions
- revision direction
- consensus bias / dispersion
- recency
- coverage depth
- whether the change is actionable or stale

## Data source policy

### Event intelligence sources
Preferred source order:
1. **Finnhub** — earnings calendar and event-style coverage
2. **Financial Modeling Prep (FMP)** — earnings, dividends, splits, corporate events
3. **SEC EDGAR** — filings, 8-K, 10-Q, 10-K, insider forms, material event evidence
4. **Company investor relations / exchange calendars** where available

### Options intelligence sources
Preferred source order:
1. **Polygon** — options chains, open interest, greeks, IV context
2. **Tradier** — options chains and greeks
3. **ORATS** — options analytics / volatility features
4. **Intrinio** — options market data
5. **True flow vendors** (for actual flow, not just chain context): Unusual Whales, FlowAlgo, Cheddar Flow, similar licensed feeds

### Analyst intelligence sources
Preferred source order:
1. **Finnhub** — recommendations / analyst targets
2. **FMP** — analyst estimates and revisions when available
3. **Benzinga** — upgrades/downgrades / target changes
4. **IEX Cloud** — supplemental analyst data
5. **Premium institutional vendors** if already licensed later

### Source selection rules
- Prefer one strong source over multiple weak duplicates.
- A source is not “better” just because it is premium; it must be usable, current, and licensable.
- If a premium source is unavailable, fall back to normalized partial coverage instead of failing the whole analysis.
- True options flow must not be implied when only options-chain context is available.

## Integration with the rest of analysis

The market-intelligence layer should feed into existing analysis surfaces, not create a separate parallel score system.

### 1. Ticker deep analysis
Add the layer to the ticker analysis payload so it can be reviewed alongside:
- technical features
- news/context
- sentiment
- transmission analysis
- diagnostics

### 2. Plan framing
Use the layer as an evidence input to:
- `confidence_components`
- `transmission_summary`
- `setup_family`
- `action_reason`
- `risks`
- `warnings`
- narrative/evidence summaries

### 3. Confidence rules
The layer should influence confidence only through bounded contributions.

Recommended semantics:
- **Event intelligence** can lift or reduce confidence materially because it affects catalyst timing.
- **Analyst intelligence** can lift or reduce confidence moderately because it helps confirm direction or valuation pressure.
- **Options intelligence** should mainly affect execution quality, pressure, and invalidation risk; it should usually be a smaller contributor to direction than event or price context.

Important:
- do not double-count the same catalyst through news + event + analyst + options
- if multiple subdomains describe the same story, treat them as corroboration, not additive repetition
- conflicting evidence should lower confidence and add conflict flags

### 4. Transmission rules
Use the market-intelligence layer to answer:
- is there a concrete catalyst?
- is the catalyst fresh or stale?
- is the market already pricing the move?
- does the options market imply near-term pressure or decay?
- do analyst changes strengthen or weaken the same direction?

### 5. Setup-family rules
The layer may sharpen, but not invent, setup-family labels.

Examples:
- earnings + positive price response + supportive options pressure may reinforce **catalyst follow-through**
- downgrade + bearish options pressure + weak technicals may reinforce **mean reversion** or **no action**
- stale event data should not create a catalyst family by itself

## Confidence integration model

Use bounded deltas, not unconstrained scoring.

Suggested behavior:
- event intelligence: larger effect when the event is imminent and the setup depends on it
- options intelligence: moderate effect when expiry/IV/volume align with the expected move window
- analyst intelligence: moderate effect when the revision is recent and the coverage is meaningful
- coverage gaps, stale data, or conflicting evidence should subtract confidence or add warnings

Suggested safety caps:
- no single subdomain should dominate the full plan confidence alone
- no subdomain should be able to force an actionable plan if the underlying technical/setup evidence is weak
- if market intelligence is missing, the system should degrade gracefully rather than inventing confidence

## Replay and staleness rules

All market-intelligence data must be as-of aware.

Requirements:
- historical replay must only use snapshots available at or before the replay timestamp
- live analysis may use fresh provider data, but the snapshot must still record the as-of timestamp and provider freshness
- future events must not leak into replay analyses
- event dates, options chains, and analyst revisions must be versioned enough to reconstruct the decision state

## Storage and payload expectations

The system should persist both:
- normalized fields for scoring and review
- raw provider references or trimmed payloads for audit/debugging

Prefer keeping raw vendor payloads out of summary rows, but make them available in detail views and debug payloads.

Recommended persistence surfaces:
- market-intelligence snapshot record(s)
- `analysis_json`
- `TickerSignalSnapshot.source_breakdown`
- `TickerSignalSnapshot.diagnostics`
- `RecommendationPlan.signal_breakdown`
- `RecommendationPlan.evidence_summary`
- run artifact payloads

## Diagnostics and warnings

The layer should surface explicit warnings for:
- no event coverage
- stale event coverage
- no options coverage
- thin options coverage
- no analyst coverage
- stale analyst revisions
- conflicting signals across subdomains
- source failures or provider exclusions

A missing subdomain should usually be a warning, not a hard failure, unless the user explicitly requested that subdomain as mandatory.

## UI expectations

The operator should be able to see, at minimum:
- active or next event
- options pressure / IV context
- analyst revision bias
- freshness and source coverage
- whether the layer helped or hurt confidence

This should appear in:
- ticker detail / deep analysis views
- plan detail views
- any quality/calibration view that compares expected confidence to realized outcomes

## Backtesting and evaluation

Before the layer influences promotion decisions, the app should measure whether it improves:
- win rate by setup family
- realized return by confidence bucket
- false-positive rate for high-confidence plans
- actionability gap
- catalyst follow-through outcomes
- replay consistency

Validation should compare:
- plans with market intelligence present vs absent
- plans with event confirmation vs event conflict
- plans with options confirmation vs options conflict
- plans with analyst confirmation vs analyst conflict

Do not ship confidence boosts until the layer shows measurable lift on historical outcomes.

## Implementation phases

### Phase 1: event intelligence
- ingest earnings and major scheduled catalysts
- attach normalized event fields to ticker analysis
- add replay-safe staleness checks
- expose operator-visible diagnostics

### Phase 2: options context
- ingest chain/IV/OI context
- derive pressure and decay signals
- keep true flow separate from chain context
- expose freshness and spread-quality warnings

### Phase 3: analyst intelligence
- ingest rating / target / estimate revisions
- compute recency-weighted directional bias
- integrate with confidence and setup-family review

### Phase 4: calibrated fusion
- add bounded scoring contributions
- add conflict detection and de-duplication
- measure effect in calibration and walk-forward tooling

### Phase 5: UI and promotion gating
- surface the new layer in detail pages and diagnostics
- require positive evidence before using it to lift confidence materially
- promote only after backtests show improvement

## Test requirements

The test suite should prove at least:
- each subdomain can be missing without breaking the full analysis
- replay analyses do not leak future events, option states, or analyst revisions
- event, options, and analyst data each appear in the expected analysis payloads
- conflicting evidence reduces confidence or adds warnings instead of double counting
- stale coverage is reported explicitly
- confidence contributions remain bounded
- the layer does not manufacture actionable confidence from weak technical evidence

## Decision rule

If a source set cannot improve decision quality after calibration and backtesting, it should remain a diagnostic aid rather than a confidence driver.

The target is better decisions, not more fields.
