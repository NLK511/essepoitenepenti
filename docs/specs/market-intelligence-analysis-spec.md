# Market intelligence analysis spec

**Status:** current + target behavior

Binding reference for the optional market-intelligence layer: event, options, and analyst evidence used by ticker analysis and plan framing.

## Problem and goal

The current stack uses price history, technical features, news/social context, macro/industry context, transmission, and calibration. It still lacks structured short-horizon evidence from:
- corporate/event calendars
- options context or options-flow pressure
- analyst revisions/rating/target changes

Goal: add a conservative, replay-safe evidence layer that answers:
1. What event is active or imminent?
2. What do options imply about expectation, pressure, and risk?
3. What do analysts imply about direction or valuation?
4. Does this strengthen or weaken the existing trade idea?

This layer may modify confidence only when evidence is current, relevant, bounded, and aligned. It must warn or reduce confidence on stale/conflicting evidence.

## Current behavior

A partial `MarketIntelligenceService` exists and is experimental:
- disabled by default
- disabled snapshots use `coverage_status=disabled`
- disabled/unavailable snapshots contribute `0.0` confidence and no supporting/conflicting narrative strength
- enabled snapshots use yfinance-style limited event/options/analyst context
- ticker deep analysis can carry the payload for review
- replay/as-of historical snapshots are unavailable without stored vendor snapshots and must not fetch live data for old dates
- no canonical market-intelligence snapshot table exists yet
- no Settings API/UI toggle exists yet

Operator UI must display disabled snapshots as “Market intelligence disabled” rather than active evidence.

## Non-goals

Market intelligence is not:
- a replacement for technical analysis
- a standalone prediction engine
- a reason to add premium vendors before value is proven
- permission to call options-chain context “true flow”

## Canonical model

Use one layer named **market intelligence** with three normalized subdomains:
- **event intelligence**
- **options intelligence**
- **analyst intelligence**

Canonical snapshot fields:
- `ticker`, `as_of`, `source_set`
- `coverage_status`, `freshness_status`
- `event_intelligence`, `options_intelligence`, `analyst_intelligence`
- `confidence_contribution`
- `conflict_flags`, `warnings`
- `provider_diagnostics`
- `raw_payload_refs`

### Event intelligence

Capture earnings date/timing, guidance/investor/product/conference events, splits/dividends/M&A/FDA/court/SEC/other catalyst class, imminence window, past/pending/stale state, expected transmission window, and saliency/catalyst strength.

### Options intelligence

Capture chain coverage, IV/IV rank/IV change, open-interest changes, unusual volume/contract concentration, call-put/skew pressure, put-call pressure, liquidity/spread quality, expiry alignment, and true-flow fields only when an actual flow vendor is used.

### Analyst intelligence

Capture rating changes, price-target changes, estimate revisions, revision direction, consensus bias/dispersion, recency, coverage depth, and stale/actionable state.

## Data source policy

Preferred event sources:
1. Finnhub
2. Financial Modeling Prep
3. SEC EDGAR
4. company IR / exchange calendars

Preferred options sources:
1. Polygon
2. Tradier
3. ORATS
4. Intrinio
5. true-flow vendors such as Unusual Whales, FlowAlgo, Cheddar Flow when licensed

Preferred analyst sources:
1. Finnhub
2. Financial Modeling Prep
3. Benzinga
4. IEX Cloud
5. premium institutional vendors if already licensed

Rules:
- prefer one strong usable/licensed source over weak duplicates
- premium does not automatically mean better
- fall back to partial normalized coverage instead of failing full analysis
- never imply true options flow from chain-only data

## Integration contract

Market intelligence feeds existing analysis, not a parallel score.

Ticker deep analysis payload must expose it alongside technical features, news/context, sentiment, transmission, and diagnostics.

Plan framing may use it in:
- `confidence_components`
- `transmission_summary`
- `setup_family`
- `action_reason`
- `risks`
- `warnings`
- narrative/evidence summaries

Confidence semantics:
- event intelligence may lift/reduce confidence materially when catalyst timing matters
- analyst intelligence may lift/reduce confidence moderately when recent and meaningful
- options intelligence usually affects execution quality, pressure, and invalidation risk more than direction
- do not double-count the same story across news/event/analyst/options
- treat corroboration as confirmation, not additive repetition
- conflicts lower confidence and add flags

Transmission questions:
- is there a concrete fresh/stale catalyst?
- is the market already pricing it?
- do options imply near-term pressure/decay?
- do analyst changes support or challenge the direction?

Setup-family use:
- may sharpen, not invent, a family
- stale event data must not create a catalyst family by itself
- examples: earnings + positive response + supportive options may reinforce catalyst follow-through; downgrade + bearish pressure + weak technicals may reinforce mean reversion or no-action

## Confidence and safety caps

Use bounded deltas only:
- no subdomain can dominate total plan confidence alone
- no subdomain can force actionability when technical/setup evidence is weak
- missing coverage degrades gracefully
- stale/conflicting evidence subtracts confidence or warns
- disabled market intelligence contributes zero

Do not ship material confidence boosts until historical evaluation shows measurable lift.

## Replay and staleness

All data must be as-of aware:
- replay may use only snapshots available at or before replay timestamp
- live analysis records provider as-of and freshness
- future events/options/analyst changes must not leak into old decisions
- event dates, option chains, and analyst revisions must be versioned enough to reconstruct decision state

## Storage and payloads

Persist normalized fields for scoring/review and raw provider references or trimmed payloads for audit/debugging. Keep raw vendor payloads out of summary rows but available in detail/debug views.

Recommended surfaces:
- canonical market-intelligence snapshot records
- `analysis_json`
- `TickerSignalSnapshot.source_breakdown`
- `TickerSignalSnapshot.diagnostics`
- `RecommendationPlan.signal_breakdown`
- `RecommendationPlan.evidence_summary`
- run artifacts

## Diagnostics and UI

Warnings should cover:
- no/stale event coverage
- no/thin options coverage
- no/stale analyst coverage
- conflicting subdomain signals
- source failures or provider exclusions

Missing subdomains are usually warnings, not hard failures, unless explicitly required by operator settings.

Operator UI should show active/next event, options pressure/IV context, analyst revision bias, freshness/source coverage, and whether the layer helped or hurt confidence. It should appear in ticker/detail plan views and quality/calibration views where expected confidence is compared with outcomes.

## Backtesting and promotion evidence

Before market intelligence influences promotion decisions, measure lift in:
- win rate by setup family
- realized return by confidence bucket
- false-positive rate for high-confidence plans
- actionability gap
- catalyst follow-through outcomes
- replay consistency

Compare present vs absent, event confirmation vs conflict, options confirmation vs conflict, and analyst confirmation vs conflict.

If a source set cannot improve calibrated/backtested decision quality, keep it as diagnostics only.

## Implementation phases

1. **Event intelligence:** earnings/major scheduled catalysts, normalized fields, replay-safe staleness, diagnostics.
2. **Options context:** chain/IV/OI context, pressure/decay signals, true-flow separation, spread/freshness warnings.
3. **Analyst intelligence:** rating/target/estimate revisions and recency-weighted bias.
4. **Calibrated fusion:** bounded contributions, conflict detection, de-duplication, calibration/walk-forward measurement.
5. **UI and gating:** detail-page surfacing, positive-evidence requirement for lifts, promotion only after measured improvement.

## Test requirements

Tests should prove:
- each subdomain can be missing without breaking analysis
- replay does not leak future events/options/analyst revisions
- event/options/analyst data appears in expected payloads
- conflicts warn or reduce confidence instead of double-counting
- stale coverage is explicit
- confidence contributions stay bounded
- weak technical evidence cannot become actionable solely from market intelligence

## Decision rule

Market intelligence exists to improve measured decisions, not to add fields. Until proven, it remains disabled-by-default, bounded, and diagnostic-first.
