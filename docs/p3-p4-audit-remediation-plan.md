# P3/P4 audit remediation plan

**Status:** active implementation record

This plan implements the P3 architecture-simplification and P4 documentation-cleanup recommendations from `audits/full-project-spec-code-audit-2026-05-10.md`.

## P3 — Architecture and logic simplification

Goal: reduce duplicate logic and unnecessary active surfaces without changing trading behavior.

Implemented in this pass:
- removed a dead duplicate `_relationship_summary()` implementation from `WatchlistOrchestrationService`; the later richer relationship formatter remains the single implementation
- added `tests/test_watchlist_plan_framing_parity.py` to freeze the current plan-framing payload contract before extracting plan framing from orchestration
- extracted plan payload construction into `WatchlistPlanFramingService`; `WatchlistOrchestrationService` now delegates plan framing while keeping compatibility wrappers for existing callers/tests
- extracted decision-sample persistence into `WatchlistDecisionSampleService`; `WatchlistOrchestrationService` now delegates audit/tuning sample writes while preserving compatibility wrappers for helper tests
- extracted ticker-signal snapshot construction into `WatchlistSignalBuilder`; `WatchlistOrchestrationService` now delegates signal payload building while preserving the existing wrapper
- kept deeper helper extraction conservative because the remaining large-service seams affect persisted plan payloads and need broader regression if changed

Remaining safe next seams:
- extract technical feature calculation from `TickerDeepAnalysisService` / `ProposalService`
- keep `policy_health` as the headline quality contract and avoid adding another summary layer

## P4 — Documentation consolidation

Goal: make current behavior understandable without reading `docs/redesign/` as a second architecture tree.

Implemented in this pass:
- merged stable redesign principles into `product-thesis.md`
- merged the four-layer target architecture into `architecture.md`
- merged transmission modeling, setup-family playbook rules, and calibration governance into `recommendation-methodology.md`
- merged UI decluttering/navigation principles into `operator-page-field-guide.md`
- merged persistence direction and diagnostics-as-data principles into `er-model.md`
- moved historical redesign source docs into `docs/archive/redesign/` for provenance after their stable content was merged
- updated `docs/docs-index.md` so canonical docs are the main reading path

Rules followed:
- no valuable redesign material was deleted
- canonical docs now own current behavior and stable target principles
- archived redesign docs remain available for history, not active product truth
