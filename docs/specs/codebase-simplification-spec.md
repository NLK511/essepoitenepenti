# Codebase simplification spec

**Status:** current contract

This spec defines how simplification work is considered complete. Simplification must reduce maintenance risk without changing trading behavior, safety gates, persisted payload compatibility, or operator-visible semantics unless another spec explicitly changes those contracts.

## Required behavior

- Specs remain authoritative before behavior changes.
- Public API payload keys, stored payload readability, broker/risk safety gates, and run/job semantics must be preserved.
- Compatibility paths may be removed only after reference search and tests show no runtime dependency, or after the compatibility behavior is replaced by an explicit fail-fast error.
- Large test-file moves must not change assertions or shared fixture semantics.
- Common helper extraction must be pure and behavior-preserving.

## Current simplification state

The broad simplification push is complete. Remaining work is bounded maintenance:

1. Remove proven-dead compatibility paths.
2. Keep large test modules from growing by moving future domain tests into focused files; split existing large files only when touching those domains.
3. Extract macro/industry refresh common helpers only when the helper is pure and preserves existing snapshot payload keys.
4. Avoid further broker/execution splitting unless new live broker paths make current seams hard to reason about.

## Acceptance

A simplification change is acceptable when:

- focused tests for the touched area pass;
- no API/persistence compatibility is lost without a spec update;
- `git diff --check` is clean;
- broader backend and frontend validation are run before larger pushes.
