# Nitter Social Sentiment Design

This document describes the first implementation pass for adding Nitter-backed social ingestion to Trade Proposer App and the longer-term path toward fused macro, industry, and ticker sentiment.

## Objectives

- ingest tweet-like market posts from a local Nitter instance
- normalize news and social content into a unified signal schema
- preserve the signal integrity policy by making missing social coverage explicit
- prepare the pipeline for future macro / industry / ticker sentiment fusion

## First-pass architecture

The first pass introduces four new building blocks:

1. `SignalItem` / `SignalBundle` domain models in `src/trade_proposer_app/domain/models.py`
2. `NitterProvider` and `SocialIngestionService` in `src/trade_proposer_app/services/social.py`
3. `SignalIngestionService` in `src/trade_proposer_app/services/signals.py`
4. social settings + preflight reachability checks for the local Nitter instance

The proposal pipeline still uses the existing news-native sentiment score for recommendation generation in this first pass, but it now persists unified signal diagnostics under `analysis_json.signals` and `analysis_json.social`.

## Current first-pass behavior

- News sentiment remains the scoring source used by the proposal engine.
- Social/Nitter content is fetched separately and persisted as structured diagnostics.
- `analysis_json.sentiment.macro` and `analysis_json.sentiment.industry` are placeholders for the upcoming hierarchical fusion work.
- `analysis_json.sentiment.ticker.source_breakdown.social.item_count` now reports how much social coverage was present for the ticker.

## Nitter configuration

The app stores the following settings:

- `social_sentiment_enabled`
- `social_nitter_enabled`
- `social_nitter_base_url`
- `social_nitter_timeout_seconds`
- `social_nitter_max_items_per_query`
- `social_nitter_query_window_hours`
- `social_nitter_include_replies`
- source and scope weighting placeholders for future fusion

Use `http://127.0.0.1:8080` when the app and Nitter share the same VPS.

## Preflight behavior

`/api/health/preflight` now also checks:

- whether `ticker_taxonomy.json` exists
- whether Nitter is reachable when social ingestion is enabled

If Nitter is disabled, preflight emits a warning instead of failing.

## Next implementation phases

### Phase 1 complete in this pass
- social settings support
- Nitter provider scaffold
- unified signal models
- signal diagnostics persisted into the proposal payload
- Nitter reachability in preflight

### Phase 2
- parse and classify macro / industry / ticker queries separately
- add taxonomy-driven query profiles
- score social items rather than just persisting them

### Phase 3
- implement hierarchical fusion:
  - macro sentiment
  - industry sentiment
  - ticker sentiment
  - overall fused sentiment

### Phase 4
- add new feature-vector fields and weights
- expose social / fused sentiment cards in the UI
- tune with evaluation results
