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

5. **Large test modules**
   - Problem: repository and route tests are hard to navigate.
   - Safe next step: split by domain with no assertion changes.

## Dead-code audit candidates

Latest audit: `dead-code-audit-2026-05-29.md`.

Do not delete until references and tests prove safe:
- `TickerDeepAnalysisService._analyze_with_compatibility_fallback`
- deprecated job-type aliases
- legacy provider observability compatibility events
- legacy proposal helper paths still imported by tests/compatibility callers

## Acceptance criteria for each refactor

- Same API payload keys unless spec says otherwise.
- Same repository persistence semantics.
- Same safety gates for broker/risk/promotion code.
- Focused tests pass for touched area.
- Full backend tests and frontend typecheck pass before pushing code changes.
