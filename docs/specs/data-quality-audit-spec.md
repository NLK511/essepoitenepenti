# Data Quality Audit Spec

**Status:** current behavior

## Goal
Surface repeated market-data, news-coverage, and broker-tradability problems before they distort recommendation quality or waste broker submissions.

## Source of truth
The audit reads from persisted records:
- `watchlists` for the tickers currently in scope
- `historical_market_bars` for bar coverage
- `historical_news_items` for ticker news coverage
- `broker_order_executions` for broker reject/failure evidence

## Buckets
The audit reports each ticker with:
- bar count and latest bar timestamp
- news count and latest news timestamp
- broker reject count and latest reject message
- affected watchlists
- issue labels:
  - `no_bars`
  - `stale_bars`
  - `no_news`
  - `stale_news`
  - `broker_rejected`

Missing coverage and broker untradability must remain separate labels. A ticker with no bars is not automatically considered broker-untradable, and a broker asset-not-found rejection is not automatically considered a news-coverage failure.

## Endpoint
`GET /api/data-quality/audit`

Query parameters:
- `watchlist_id` optional watchlist filter
- `ticker` optional ticker filter
- `limit` maximum number of issue rows
- `stale_after_days` coverage freshness threshold

## Semantics
Only tickers with at least one issue label are returned in `items`.

The response also includes aggregate bucket counts so operators can identify whether the dominant problem is missing coverage, stale coverage, or broker tradability.
