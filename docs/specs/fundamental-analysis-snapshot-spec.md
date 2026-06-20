# Fundamental analysis snapshots

**Status:** current + target behavior

Weekly weekend and event-aware fundamental snapshots for monitored tickers. Persistence, refresh jobs/routes, point-in-time lookup, ticker/plan integration, compact payloads, and initial validation-slice plumbing are implemented. Dedicated stale-coverage UI/observability polish and action-affecting positive contribution remain target behavior pending validation.

## Goal

The app should periodically collect a point-in-time fundamental view for every monitored ticker and make that view available to ticker analysis, plan generation, filtering, and later validation.

Fundamentals are slower-moving than price/news. They should initially act as context, risk filters, and setup classification inputs, not as unproven confidence boosters.

## Scope

A monitored ticker is any ticker that appears in at least one active watchlist or has recent app-owned broker exposure.

The snapshot covers:
- business profile: sector, industry, market-cap bucket, exchange, currency
- valuation: market cap, trailing/forward PE when available, price-to-sales, price-to-book, enterprise-value ratios when available
- profitability/quality: gross margin, operating margin, net margin, return on equity/assets when available
- growth: revenue growth, earnings growth, EPS trend when available
- balance sheet/risk: debt/equity, current ratio, cash/debt when available
- cash flow: operating/free cash flow proxy when available
- analyst context: recommendation mean/key, target price/upside, recent recommendation changes when available
- event calendar: next earnings date/window, ex-dividend date, shareholder meeting/annual meeting/proxy dates when available, other major corporate events if available
- data quality: source coverage, missing fields, stale fields, provider errors, point-in-time timestamp

## Refresh schedule

Baseline cadence:
- run the default refresh jobs weekly during the weekend, when proposal-generation load is lower and markets are closed
- spread the weekend refresh across multiple capped batches so provider quotas are not hit by one large burst
- refresh each monitored ticker at least once per month through due-snapshot logic; weekly batch jobs must safely skip still-fresh snapshots

Event-aware cadence:
- refresh earlier when a known important corporate event is near or just happened
- examples: earnings release, guidance update, shareholder/annual meeting, dividend/ex-dividend date, split, merger vote, investor day, major SEC filing, FDA/court/regulatory event for relevant industries

Recommended event windows:
- pre-event: 14 days before known earnings/shareholder/investor-day events
- event week: every trading day from 3 trading days before through 2 trading days after the event
- post-event: one follow-up refresh 7 calendar days after the event if no newer snapshot exists

If provider data cannot supply event dates, the weekly weekend batch refresh still runs and marks event coverage unavailable.

## Point-in-time and storage rules

Snapshots must be stored as immutable point-in-time records. Never overwrite historical snapshot payloads.

Each snapshot records:
- ticker
- `as_of`
- source/provider names
- normalized feature payload
- raw compact provider payload references when safe
- coverage status: `ok`, `degraded`, `blocked`, `disabled`
- freshness status: `fresh`, `stale`, `unknown`
- warnings and missing inputs
- job/run ids when created by a scheduled job

Plan generation must attach the latest snapshot available at or before plan creation time. It must not use snapshots created after the plan timestamp.

## Plan-analysis integration

Ticker deep analysis and watchlist plan generation should receive the latest point-in-time fundamental snapshot and expose a compact fundamental section in:
- ticker analysis payload
- transmission summary when relevant
- signal breakdown
- evidence summary
- raw details

Initial decision role:
- can lower confidence or force caution when fundamental risk is severe and relevant to the setup
- can classify setup context, e.g. earnings-event setup, valuation-risk breakout, balance-sheet-risk reversal
- must not materially increase confidence until validated
- must not override fresh price/actionability/broker-risk gates

Suggested bounded use:
- upcoming earnings inside the intended holding window should warn or raise the action threshold unless the strategy explicitly supports earnings-event trades
- severe analyst/guidance deterioration should act as a risk flag for longs and possible support for shorts only when fresh and source-backed
- strong static fundamentals may be displayed but should not boost short-horizon confidence by default

## Validation plan

Validation must prove usefulness before fundamentals become a positive confidence driver.

Required slices:
- earnings within 3/7/14 days vs no near event
- post-earnings 0-2d, 3-7d, 8-14d windows
- analyst upgrade/downgrade/reiteration/none
- positive/negative target-price upside bucket
- valuation bucket high/medium/low relative to sector when available
- profitability/quality bucket high/medium/low
- leverage/balance-sheet-risk bucket
- setup family + fundamental event regime

Metrics:
- broker-preferred effective win rate
- expected value / average return when available
- false-positive reduction
- entry-touch and no-entry behavior
- drawdown/loss-streak behavior
- comparison to baseline without the fundamental rule

Rules:
- use walk-forward validation; do not promote in-sample-only effects
- require enough resolved samples before slice-driven gating
- start with risk filters and threshold increases, not positive boosts
- preserve raw feature snapshots so future validation can recompute cohorts

## Implementation status

Implemented current behavior:

1. Schema and repository
   - immutable `fundamental_analysis_snapshots`
   - latest ticker snapshot, point-in-time lookup, latest-by-ticker, and stale monitored ticker helpers

2. Service
   - `FundamentalAnalysisService` normalizes provider data into the snapshot schema
   - sparse and provider-limited payloads are marked degraded/blocked with warnings rather than healthy

3. Job and API
   - `fundamental_analysis_refresh` job type and default weekend refresh cadence
   - manual/API refresh, due monitored ticker refresh, monitored ticker listing, and validation-slice summary

4. Integration
   - latest point-in-time snapshot is injected into ticker deep analysis and watchlist plan framing
   - compact fundamental context is persisted in plan signal/evidence payloads
   - confidence role is conservative by default and does not positively boost confidence

5. UI and validation
   - ticker/plan views expose compact fundamental coverage/event/valuation context
   - initial validation slices use broker-preferred effective outcomes and persisted plan signal-breakdown buckets

Still target / gated:

- dedicated stale-coverage UI and richer observability events
- expected-value/drawdown extensions for fundamental validation slices
- action-affecting positive contribution or valuation-based caps, pending point-in-time walk-forward evidence

## Current non-goals

- Do not build a full fundamental factor model in v1.
- Do not use unversioned live fundamentals to explain historical plans.
- Do not add many free tuning knobs before passive validation.
- Do not let static valuation or quality metrics dominate short-horizon price/news evidence.
