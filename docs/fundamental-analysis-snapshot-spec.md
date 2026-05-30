# Fundamental analysis snapshots

**Status:** target behavior

Monthly and event-aware fundamental snapshots for monitored tickers.

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
- refresh each monitored ticker at least once per month

Event-aware cadence:
- refresh earlier when a known important corporate event is near or just happened
- examples: earnings release, guidance update, shareholder/annual meeting, dividend/ex-dividend date, split, merger vote, investor day, major SEC filing, FDA/court/regulatory event for relevant industries

Recommended event windows:
- pre-event: 14 days before known earnings/shareholder/investor-day events
- event week: every trading day from 3 trading days before through 2 trading days after the event
- post-event: one follow-up refresh 7 calendar days after the event if no newer snapshot exists

If provider data cannot supply event dates, monthly refresh still runs and marks event coverage unavailable.

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

## Implementation phases

1. Schema and repository
   - add immutable `fundamental_analysis_snapshots`
   - repository methods for latest ticker snapshot at/before timestamp and stale-monitored-ticker discovery

2. Service
   - `FundamentalAnalysisService` normalizes provider data into the snapshot schema
   - default provider can reuse yfinance-derived fields, but payloads must mark coverage limitations

3. Job
   - add `fundamental_analysis_refresh` job type or equivalent scheduled path
   - seed monthly refresh job
   - add event-aware candidate prioritization

4. Integration
   - inject latest snapshot into ticker deep analysis and watchlist plan framing
   - persist compact fundamental payload in plan signal/evidence payloads
   - keep confidence role conservative by default

5. Observability and UI
   - show latest snapshot timestamp, event calendar status, warnings, and compact feature buckets
   - record provider failures and stale coverage

6. Validation
   - add cohort/slice reports before enabling any positive confidence contribution

## Current non-goals

- Do not build a full fundamental factor model in v1.
- Do not use unversioned live fundamentals to explain historical plans.
- Do not add many free tuning knobs before passive validation.
- Do not let static valuation or quality metrics dominate short-horizon price/news evidence.
