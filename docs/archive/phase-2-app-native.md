# Phase 2: App-native Outcomes

**Status:** historical reference

This document tracks the part of the roadmap concerned with keeping Trade Proposer App self-contained. Phase 2 is no longer about proving that app-native execution is possible; it is about making the internal pipeline trustworthy, inspectable, and operationally reliable.

## Governing principle: signal integrity

Every contribution that affects recommendation generation must be explicit when data is missing. The pipeline never invents a directional signal when its raw inputs are absent: missing keyword coverage, provider failures, stale snapshots, or aggregator gaps must either emit `NEUTRAL`/zero outputs or surface a digestible warning before a new score is published.

This principle remains the correct constraint for Phase 2 because it prevents invisible quality regressions disguised as graceful fallbacks.

## What Phase 2 has already delivered

- **Self-contained scoring**: `ProposalService` orchestrates price ingestion, feature construction, normalization, weighting, and diagnostics entirely inside this repository.
- **App-native evaluation**: the evaluation workflow uses the same `yfinance`-derived price history as proposal generation and persists outcomes in the app.
- **App-native optimization**: the optimization workflow reads resolved `RecommendationPlanOutcome` records from the app database, adjusts the tracked `weights.json`, and stores backup metadata without depending on a prototype repo.
- **Structured diagnostics**: each run persists `analysis_json`, feature vectors, aggregations, confidence weights, and run diagnostics in a stable backend-owned shape.
- **UI inspection**: run detail and recommendation-plan-centered operator views render structured diagnostics directly instead of exposing only raw JSON.
- **Configurable summarization**: the summary service supports digest-only output, OpenAI, and `pi_agent`, while preserving backend/model/runtime metadata and explicit errors.
- **Shared sentiment snapshots**: macro and industry sentiment are now refreshed as first-class workflows, stored as `SentimentSnapshot` records, reused during proposal generation, linked from detail pages, and checked by health/preflight for freshness.
- **Coverage transparency**: neutral outputs still explain themselves through `coverage_insights`, `keyword_hits`, provider errors, and snapshot freshness warnings.

## Where Phase 2 is effective

Phase 2 is working best where it has removed cross-system ambiguity:
- one repo owns scoring, evaluation, optimization, and diagnostics
- one run system records the operational history
- one UI exposes both the trade outputs and the reasons behind them
- one signal-integrity rule governs missing or degraded inputs

That is a strong foundation. It means future changes can be judged against a shared contract instead of against prototype behavior.

## Where Phase 2 is still weak

The remaining weaknesses are mostly about operational confidence, not missing features:
- scheduler/worker behavior still needs stronger guarantees for overlap handling and crash recovery
- production observability is not yet strong enough for a workflow system with multiple background processes
- the sentiment stack is more inspectable than it is validated; quality measurement still lags behind feature delivery
- provider and credential lifecycle work is still behind the app's runtime ambitions

## What should not happen next

Phase 2 should not expand by piling on new sentiment sources or new heuristics without a measurement loop. The app now has enough sentiment structure that indiscriminate feature growth would increase complexity faster than it increases trust.

Specifically, avoid:
- adding new providers before credential lifecycle and observability improve
- introducing fallback heuristics that blur missing coverage
- duplicating the same future plan across roadmap, feature docs, and implementation notes

## Next steps

1. harden scheduler and worker reliability for overlapping and recovering workloads
2. improve observability around run execution, refresh workflows, and provider failures
3. measure whether shared snapshots and enhanced sentiment improve recommendation outcomes before broadening the provider surface
4. keep docs aligned with the live schema and remove planning language once a feature is already shipped
