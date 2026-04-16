# News provider eligibility spec

Status: implemented in progress

## Problem

The app uses time windows for both:
- live workflows such as macro context refresh, industry context refresh, and recommendation generation
- replay / reconstruction workflows that must avoid pulling present-day data into past windows

The old eligibility rule treated any request with `start_at` / `end_at` as replay-like and filtered providers only by a single `historical_replay_safe` flag.

That caused a live macro context bug:
- macro context uses topic queries plus a 24h window
- Finnhub is replay-safe but does not support topic queries
- Google News supports topic queries but is not replay-safe
- NewsAPI is disabled by default
- result: zero eligible providers and a misleading `news: no providers configured` warning even when credentials existed

## Required behavior

Provider selection must be driven by explicit request semantics, not by the mere presence of a time window.

## Request semantics

Every news fetch must evaluate provider eligibility from these dimensions:
- `query_type`: `ticker` or `topic`
- `request_mode`: `live` or `replay`
- `windowed`: whether `start_at` or `end_at` is present
- `primary_only`: whether the caller wants only providers that count as primary-news evidence

## Provider capabilities

Every provider must declare capabilities independently.

Required capability flags:
- `supports_ticker`
- `supports_topic`
- `supports_live_windowed_queries`
- `supports_replay_windowed_queries`
- `counts_as_primary_news`

The old `historical_replay_safe` flag is not the source of truth anymore.

## Selection rules

### Base rule
A provider is eligible only if it satisfies all required dimensions for the request.

### Query type
- ticker requests require `supports_ticker = true`
- topic requests require `supports_topic = true`

### Windowed live requests
If a request is windowed and `request_mode = live`, the provider must satisfy:
- `supports_live_windowed_queries = true`

This must not require replay support.

### Windowed replay requests
If a request is windowed and `request_mode = replay`, the provider must satisfy:
- `supports_replay_windowed_queries = true`

### Primary-only requests
If `primary_only = true`, the provider must satisfy:
- `counts_as_primary_news = true`

## Workflow requirements

### Macro context
- must request topic news with `request_mode = live`
- must request `primary_only = true`
- must keep the 24h window behavior

### Industry context
- must request primary news with `request_mode = live`
- must request `primary_only = true`
- both ticker-basket and topic-query branches must use the same eligibility model

### Historical / reconstruction workflows
- must be able to request `request_mode = replay`
- replay requests must never silently fall back to live-only providers

## Diagnostics requirements

Diagnostics must distinguish between:
- no providers configured at all
- providers configured but none eligible for the request

When providers are configured but none are eligible, the error must include:
- request shape summary (`query_type`, `request_mode`, `windowed`, `primary_only`)
- exclusion reasons per provider when available

Example shape:
- `news: no providers eligible for query_type=topic mode=replay windowed=true primary_only=true`
- `news: provider exclusions: Finnhub(topic unsupported), GoogleNews(replay window unsupported)`

## Current capability expectations

### Finnhub
- supports ticker queries
- does not support topic queries
- supports live windowed queries
- supports replay windowed queries
- counts as primary news

### Google News
- supports ticker queries
- supports topic queries
- supports live windowed queries
- does not support replay windowed queries
- counts as primary news because it is a transport layer over whitelisted primary publishers

### Yahoo Finance
- supports ticker queries
- does not support topic queries
- supports live windowed queries
- does not support replay windowed queries
- does not count as primary news

### NewsAPI
- may support both query types and both window modes when enabled
- remains disabled by default unless product policy changes

## Test requirements

The unit test suite must prove at least:
- live windowed topic queries can select a live-only topic provider
- replay windowed topic queries reject live-only topic providers
- primary-only filtering excludes supporting-only providers
- macro context forwards `request_mode = live` and `primary_only = true`
- industry context forwards `request_mode = live` and `primary_only = true`
- diagnostics explain provider exclusions when eligibility fails
