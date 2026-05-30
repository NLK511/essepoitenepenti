# Codebase simplification plan

**Status:** active plan

Goal: reduce code complexity without changing product behavior, safety rules, data contracts, or operator-visible semantics.

## Rules

- Specs stay authoritative; update docs before changing behavior.
- Refactors must preserve public APIs and persisted payloads unless separately specified.
- Prefer extracting pure helpers and orchestration seams over changing domain logic.
- Keep compatibility wrappers until references are traced and removed intentionally.
- Run focused tests for touched code plus broader validation before commit.

## Current high-value targets

1. **Plan-generation tuning orchestration**
   - Problem: `PlanGenerationTuningService.run()` mixed orchestration, candidate evaluation batches, candidate persistence, promotion checks, and run finalization.
   - Done now: extracted candidate search, batch evaluation, candidate persistence, and winner-promotion helpers while preserving logs and payloads.
   - Remaining possible work: move candidate generation/evaluation/promotion policy to dedicated classes if future changes require it.

2. **Legacy proposal compatibility surface**
   - Problem: `ProposalService` is still large and acts as a dependency magnet for price history, payload building, news/context enrichment, and compatibility helpers.
   - Done now: moved shared summary defaults and JSON sanitization to `payload_utils` while keeping `ProposalService` compatibility exports.
   - Done now: extracted price-history fetch orchestration into `PriceHistoryFetcher` while preserving `ProposalService` wrapper methods for compatibility.
   - Done now: split `ProposalService._apply_news_context` into focused signal, social, summary, hierarchical-context, sentiment-payload, and no-news helper methods.
   - Done now: split `ProposalService._build_analysis_payload` into focused section builders.
   - Safe next step: audit remaining compatibility-only proposal paths before any deletion.

3. **Macro/industry context duplication**
   - Problem: refresh payload parsing, prompt construction, diagnostics, and quality/warning normalization are similar across macro and industry services.
   - Done now: extracted proposal-time macro/industry snapshot payload mapping into `context_payload_utils`.
   - Safe next step: extract common refresh/prompt diagnostics only after a focused spec pass.

4. **Broker steering execution handlers**
   - Problem: workflow execution had multiple broker mutation branches in one method.
   - Done now: split cancel, close, and exit-amendment handlers while preserving safety gates and execution statuses.

5. **Order execution orchestration**
   - Problem: `OrderExecutionService.execute_plans` mixed summary setup, client bootstrapping, per-plan execution, and summary finalization.
   - Done now: extracted summary initialization, missing-client handling, skipped-outcome creation, and final summary assembly.
   - Done now: extracted per-plan candidate/risk/submission handling and submitted-order status counting.
   - Safe next step: split `_execute_single_plan` only if more broker execution branches are added.

6. **Large test modules**
   - Problem: repository and route tests are hard to navigate.
   - Safe next step: split by domain with no assertion changes.

## Dead-code audit candidates

Latest audit: `dead-code-audit-2026-05-29.md`.

Do not delete until references and tests prove safe:
- `TickerDeepAnalysisService._analyze_with_compatibility_fallback`
- deprecated job-type aliases
- legacy provider observability compatibility events
- legacy proposal helper paths still imported by tests/compatibility callers

7. **Signal-gating tuning orchestration**
   - Problem: `RecommendationSignalGatingTuningService.run` mixed sample-window loading, scoreability checks, candidate ranking, apply behavior, and run construction.
   - Done now: extracted scored sample-window loading, candidate ranking, and winning-config application helpers.

8. **Recommendation-quality summary orchestration**
   - Problem: `RecommendationQualitySummaryService.summarize` mixed active config loading, walk-forward validation, rolling-window metric assembly, policy trust, and response construction.
   - Done now: extracted walk-forward summary and rolling-window/default-window assembly helpers.

9. **Plan resolution engine**
   - Problem: `PlanResolutionEngine.evaluate_plan` mixed setup classification, missing-data handling, no-entry diagnostics, entered-position resolution, and outcome construction.
   - Done now: extracted non-trade, pending, no-entry, entered, and entered-state outcome builders while preserving canonical resolution semantics.

10. **Watchlist signal snapshot builder**
   - Problem: `WatchlistSignalBuilder.build_signal_snapshot` mixed warning collection, transmission field normalization/fallbacks, and snapshot construction.
   - Done now: extracted warning collection and transmission field normalization helpers.

11. **Watchlist plan framing**
   - Problem: `WatchlistPlanFramingService.build_plan_from_signal` mixed framing context assembly, calibration thresholds, trade-level calculation, action gating, and plan construction.
   - Done now: extracted framing context, effective-threshold, trade-level, and action-resolution helpers while preserving parity-tested plan payloads.

12. **Summary pi-agent execution path**
   - Problem: `SummaryService._summarize_with_pi_prompt` mixed command construction, process lifecycle management, stream reading, timeout handling, output parsing, and fallback construction.
   - Done now: extracted pi command/metadata construction plus CLI process, stream, wait, and stop helpers while preserving fallback semantics and summary payload metadata.

13. **Ticker news fetch orchestration**
   - Problem: `NewsIngestionService.fetch` mixed database prefill/skip logic, provider-selection fallback, provider fetch/save/merge loops, diagnostics, observability, and cache writes.
   - Done now: extracted database prefill, no-provider finalization, provider fetch loop, ticker finalization, database article counting, and cache-write helpers while preserving query diagnostics and provider observability payloads.

14. **Plan-generation walk-forward slicing**
   - Problem: `PlanGenerationWalkForwardService.summarize_records` mixed window normalization, record ordering, slice construction, candidate/baseline comparison, aggregate deltas, promotion, and summary construction.
   - Done now: extracted window input normalization, window preparation, slice construction, per-slice comparison, win-rate delta, and average-delta helpers while preserving walk-forward math and promotion gates.

15. **Topic news fetch orchestration**
   - Problem: `NewsIngestionService.fetch_topic` mirrored ticker-fetch complexity with database prefill, provider-selection fallback, provider fetch/save/merge loops, diagnostics, observability, and cache writes inline.
   - Done now: extracted topic database prefill, no-provider finalization, provider fetch loop, and topic finalization helpers while preserving query diagnostics, cache behavior, and provider observability payloads.

16. **Ticker analysis payload assembly**
   - Problem: `TickerAnalysisPayloadService.build_analysis_payload` assembled every payload section inline, making summary/news/sentiment/proposal/technical/deep-analysis contracts hard to scan.
   - Done now: extracted section builders while preserving all analysis payload keys and values.

17. **Watchlist shortlist selection**
   - Problem: `ShortlistSelectionService.evaluate` mixed candidate ranking, eligibility rules, core selection, catalyst-lane relaxation, decision payloads, and rejection counting.
   - Done now: extracted ranking, eligibility, shortlist selection, catalyst-lane eligibility, and decision/rejection payload helpers while preserving shortlist rules and diagnostics.

## Acceptance criteria for each refactor

- Same API payload keys unless spec says otherwise.
- Same repository persistence semantics.
- Same safety gates for broker/risk/promotion code.
- Focused tests pass for touched area.
- Full backend tests and frontend typecheck pass before pushing code changes.
