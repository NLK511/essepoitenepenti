# Codebase simplification backlog

**Status:** completed implementation plan; ongoing hygiene is governed by `specs/codebase-simplification-spec.md`

Goal: keep code complexity from growing while preserving product behavior, safety rules, data contracts, and operator-visible semantics.

The broad simplification push is complete. This document records the completion decision; future simplification belongs in normal touched-area work under the spec, not as a standing active implementation plan.

## Rules

- Specs stay authoritative; update docs before changing behavior.
- Refactors must preserve public APIs and persisted payloads unless separately specified.
- Prefer extracting pure helpers and orchestration seams over changing domain logic.
- Keep compatibility wrappers until references are traced and removed intentionally.
- Run focused tests for touched code plus broader validation before commit.

## Completion decisions

### 1. Compatibility-path audit — completed

Decision:

- keep `TickerDeepAnalysisService._analyze_with_compatibility_fallback` intentionally because repository/watchlist tests still exercise generate-only deep-analysis stubs and the wrapper preserves old analysis payload readability;
- remove redundant job-type self-alias parsing;
- keep persisted-row and old-payload readers in repositories/resolvers where required.

Acceptance met:

- reference search identified compatibility callers, so the ticker fallback path remains documented rather than deleted;
- persisted rows and old payloads remain readable through repository/resolver adapters;
- focused ticker and repository tests cover current behavior.

### 2. Large test modules — converted to maintenance rule

Decision:

- do not perform a disruptive whole-file move just for line counts;
- new route/repository coverage should be added to focused domain files instead of growing `tests/test_routes.py` or `tests/test_repositories.py`;
- split existing sections opportunistically when touching that domain and when assertions can move without fixture changes.

Acceptance met for this plan:

- no behavior changed;
- the simplification spec now prevents further unchecked growth.

### 3. Macro/industry refresh commonality — bounded

Decision:

- only extract pure helper seams that preserve existing macro and industry payload keys;
- do not merge macro and industry decision semantics;
- keep industry context secondary and conservative per `specs/context-scoring-spec.md`.

Acceptance met:

- common warning/diagnostic helper extraction is allowed by spec only when behavior-preserving;
- context snapshot payload compatibility remains required.

### 4. Future broker/execution seams — deferred/no action

Order execution and broker steering have already been split into smaller helpers. Do not split further just for aesthetics.

Reopen only if:

- new broker branches make `_execute_single_plan` hard to reason about;
- steering gains live mutation paths after dry-run validation;
- reconciliation adds materially different broker-specific workflows.

Acceptance remains:

- safety gates unchanged;
- broker mutation behavior fail-closed where specified;
- broker regression tests pass.

## Completed simplification themes

The previous active plan completed many extractions across:

- plan-generation tuning and walk-forward slicing
- broker steering handlers
- order execution orchestration
- signal-gating tuning
- recommendation-quality summary assembly
- plan resolution
- watchlist signal building, framing, calibration review, shortlist selection, and cheap-scan scoring
- proposal job execution
- ticker analysis, technical context, transmission analysis, and taxonomy relationship assembly
- news fetch orchestration
- summary pi-agent execution

Do not re-document all completed refactors here. Use git history for exact diffs.

## Acceptance criteria for future hygiene refactors

- Same API payload keys unless a spec says otherwise.
- Same repository persistence semantics.
- Same safety gates for broker/risk/promotion code.
- Focused tests pass for touched area.
- Full backend tests and frontend typecheck pass before larger pushes.
