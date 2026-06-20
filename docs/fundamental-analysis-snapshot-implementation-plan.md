# Fundamental analysis follow-up plan

**Status:** active plan

This plan tracks the remaining work after the core fundamental snapshot implementation.

The original implementation is mostly shipped. Fundamental data is now point-in-time context for analysis and plan generation, not a positive confidence booster.

## Current shipped baseline

Already implemented:

- immutable `fundamental_analysis_snapshots` persistence
- latest and point-in-time snapshot lookup
- monitored ticker discovery from watchlists and app-owned broker exposure
- scheduled and manual refresh paths
- due monitored ticker refresh behavior
- normalized snapshot payloads with coverage/freshness/warning fields
- ticker analysis and plan payload integration
- compact fundamental context in recommendation-plan signal breakdowns
- initial validation-slice API using broker-preferred effective outcomes
- sparse payloads are degraded rather than marked healthy `ok`
- no positive confidence boost from fundamentals

## Current stance

Fundamentals are passive, conservative valuation and event-risk context.

They may diagnose risk, sparse evidence, event timing, valuation mismatch, or quality concerns. They must not raise live confidence until point-in-time walk-forward evidence supports that use.

Conservative threshold raises, caps, or warnings based on fundamentals require an explicit policy decision and validation. Positive boosts remain disabled.

## Remaining success criteria

- stale/sparse fundamental coverage is visible in operator-facing health surfaces
- refresh failures produce structured observability evidence
- validation slices include expected value, drawdown/loss-streak, false-positive, and no-entry behavior
- any action-affecting use is explicit, conservative, auditable, and validated

## Remaining workstreams

### 1. Stale and sparse coverage visibility

Deliverables:

- dashboard/operator health summary for stale monitored tickers
- ticker-level display of coverage, freshness, valuation bucket, event regime, and sparse-input warnings
- data-quality/debug surface for provider failures and stale monitored ticker queues

Acceptance:

- operators can see whether fundamental context is missing, stale, sparse, degraded, or usable
- sparse provider payloads cannot look healthy

### 2. Refresh observability

Observability events to emit or verify:

- `fundamental_refresh_started`
- `fundamental_snapshot_created`
- `fundamental_refresh_failed`
- `fundamental_refresh_completed`

Deliverables:

- structured event payloads with ticker, provider diagnostics, coverage state, freshness state, and failure reason
- run artifacts summarizing refreshed, skipped, stale, sparse, failed, and blocked counts

Acceptance:

- a failed or sparse refresh is diagnosable without shell access
- provider limitations are visible but redacted where needed

### 3. Richer validation slices

Slices:

- event regime
- earnings within 3/7/14 days
- analyst action/recommendation bucket when available
- valuation bucket
- profitability/quality bucket
- growth bucket
- balance-sheet-risk bucket
- setup family + event regime
- valuation bucket + setup family

Metrics:

- broker-preferred effective win rate
- expected value where available
- false-positive reduction
- loss streak and drawdown behavior
- entry-touch and no-entry behavior
- sparse-data warnings and minimum sample counts

Acceptance:

- slices show resolved counts and sparse-data warnings
- exploratory vs action-affecting conclusions are clearly separated
- no promotion of positive fundamental boosts without walk-forward evidence

### 4. Explicit action-affecting policy decision

Potential future uses, in increasing risk order:

1. operator-only warning labels
2. conservative threshold raises for specific event/valuation risk states
3. notional caps or concentration caps for degraded/sparse fundamental evidence
4. positive confidence boosts for validated valuation/quality tailwinds

Current allowed mode:

- operator warnings and passive context only

Blocked until separately validated:

- positive confidence boosts
- automatic confidence increases from valuation or quality
- broad actionability expansion based on fundamentals

Acceptance before any action-affecting use:

- at least 30 days of passive snapshots or a justified larger historical point-in-time sample
- enough resolved broker-preferred outcomes per slice
- walk-forward validation beats baseline
- no increase in drawdown/loss streak
- operator-visible sparse evidence warnings
- docs/spec update before behavior change

## Safety gates

Initial and current shipped mode remains:

- collect snapshots
- display and persist context
- warn around sparse, stale, degraded, or event-risk states
- do not boost confidence

## See also

- `specs/fundamental-analysis-snapshot-spec.md`
- `specs/fundamental-valuation-integration-spec.md`
- `recommendation-quality-improvement-plan.md`
