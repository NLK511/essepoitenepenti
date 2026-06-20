# Codebase simplification backlog

**Status:** active plan

Goal: keep code complexity from growing while preserving product behavior, safety rules, data contracts, and operator-visible semantics.

This document is now a lightweight maintenance backlog. The broad simplification push has largely completed; completed refactor history belongs in git and archived audits, not in the main reading path.

## Rules

- Specs stay authoritative; update docs before changing behavior.
- Refactors must preserve public APIs and persisted payloads unless separately specified.
- Prefer extracting pure helpers and orchestration seams over changing domain logic.
- Keep compatibility wrappers until references are traced and removed intentionally.
- Run focused tests for touched code plus broader validation before commit.

## Current live targets

### 1. Compatibility-path audit before deletion

Do not delete compatibility paths until references and tests prove safe.

Current candidates:

- `TickerDeepAnalysisService._analyze_with_compatibility_fallback`
- deprecated job-type aliases
- legacy provider observability compatibility events
- legacy proposal helper paths still imported by tests/compatibility callers

Acceptance:

- reference search shows no runtime callers, or callers are intentionally migrated
- persisted rows and old payloads remain readable
- tests cover old payload compatibility where required

### 2. Large test modules

Problem: repository and route tests are hard to navigate.

Safe next step:

- split large test modules by domain with no assertion changes
- keep fixtures shared only when reuse is clear
- avoid mixing behavior changes with test-file moves

Acceptance:

- same assertions pass after split
- no broad fixture behavior changes

### 3. Macro/industry refresh commonality

Problem: macro and industry refresh paths still share concepts around prompt construction, diagnostics, quality normalization, and warning payloads.

Safe next step:

- extract common refresh/prompt diagnostics only after a focused spec pass
- preserve existing payload keys and quality semantics
- do not make industry context look more decision-grade without validation

Acceptance:

- context snapshot payloads remain backward compatible
- warnings and degraded states remain explicit
- context service tests pass

### 4. Future broker/execution seams only when needed

Order execution and broker steering have already been split into smaller helpers. Do not split further just for aesthetics.

Reopen this target only if:

- new broker branches make `_execute_single_plan` hard to reason about
- steering gains live mutation paths after dry-run validation
- reconciliation adds materially different broker-specific workflows

Acceptance:

- safety gates remain unchanged
- broker mutation behavior remains fail-closed where specified
- broker regression tests pass

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

## Acceptance criteria for each future refactor

- Same API payload keys unless a spec says otherwise.
- Same repository persistence semantics.
- Same safety gates for broker/risk/promotion code.
- Focused tests pass for touched area.
- Full backend tests and frontend typecheck pass before larger pushes.
