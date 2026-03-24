# Roadmap

## Current status

Trade Proposer App now executes its critical workflows entirely inside this repository:
- **Persistent state**: watchlists, jobs, runs, recommendations, settings, and sentiment snapshots live in one schema and remain queryable from the UI or API.
- **Operator UI**: the React/Vite SPA provides dashboard, jobs, history, debugger, settings, docs, ticker, and sentiment pages for the core operator workflows.
- **Execution model**: the worker-backed queue persists job metadata, honors concurrency controls, and logs timing/diagnostic payloads for reproducibility.
- **Feature-rich diagnostics**: every run emits structured `analysis_json`, feature vectors, aggregations, confidence weights, warnings, and workflow summaries.
- **Shared sentiment context**: macro and industry refresh workflows persist reusable snapshots, proposal generation links back to those snapshots, and health/preflight now reports snapshot freshness.
- **Signal integrity policy**: missing data becomes explicit neutral/warning output rather than an invented fallback.
- **Redesign write path**: watchlist orchestration, cheap-scan diagnostics, ticker signals, recommendation plans, news-first transitional macro/industry context writers, and a dedicated ticker deep-analysis service now exist inside the main app execution flow.

## Phase 1: Operational hardening (partially complete)

Foundational execution is in place, but this phase should still be treated as active because production hardening is not finished.

Completed or largely in place:
- scheduler-backed queueing and atomic claiming
- structured pipeline contracts and stored diagnostics
- worker-visible warning and failure categories
- preflight guardrails for core dependencies and snapshot freshness

Still needed:
- stronger overlap and crash-recovery semantics
- clearer production health signals and structured logging
- tighter concurrency guarantees if multiple workers/processes are introduced

## Phase 2: Self-contained intelligence (mostly complete)

This phase is no longer primarily about replacing prototype dependencies; that part is mostly done.

Delivered:
- app-native proposal generation
- app-native evaluation
- app-native weight optimization
- configurable summarization via digest/OpenAI/Pi CLI
- structured diagnostics surfaced in the UI
- shared macro and industry sentiment snapshots reused during proposal generation (currently derived from social/Nitter refreshes, with news-based coverage listed as a future extension)

Remaining:
- validate the effectiveness of the expanded sentiment stack instead of only expanding it
- continue tightening UI/schema consistency as diagnostics evolve
- finish eliminating any remaining documentation drift that still describes shipped work as future work

## Phase 3: Security and production readiness

Highest-value remaining non-analytical work:
- **Credential lifecycle**: rotation, re-encryption, and optional external secret backends
- **Authentication baseline**: strengthen the single-user auth path and define the minimum acceptable operator model before adding RBAC/tenancy
- **Observability**: structured logging, run-level correlation IDs, worker/scheduler heartbeats, and deployment-facing health reporting

## Phase 4: Redesign execution path

This is now the highest-value analytical/product phase once operational hardening remains under control.

Delivered in this phase so far:
- first-class watchlist metadata aligned with trading horizons and exchange-aware scheduling
- watchlist policy inspection endpoint
- persisted redesign-domain models for:
  - macro context snapshots
  - industry context snapshots
  - ticker signal snapshots
  - recommendation plans
- repository and read API support for those new persisted objects
- real watchlist-backed cheap-scan → shortlist → deep-analysis orchestration
- dedicated cheap-scan signal model instead of recycled proposal confidence
- dedicated `TickerDeepAnalysisService` extraction so orchestration no longer calls `ProposalService` directly
- persistence of `TickerSignalSnapshot` and `RecommendationPlan` for every scanned watchlist ticker
- run-scoped API/UI visibility for redesign objects, including standalone browse pages for ticker signals and recommendation plans
- richer run artifacts that now record shortlist rules, rejection counts, and per-ticker shortlist decisions
- operator-facing shortlist reasoning surfaced more directly in run detail and ticker-signal views

Next required work in this phase:
- strengthen the current news-first context writers with better event extraction, saliency ranking, and official/trade-source coverage quality
- evolve `TickerDeepAnalysisService` from a service-boundary extraction into a genuinely redesign-native ticker-signal / recommendation-engine path
- define how the new recommendation-plan path coexists with or replaces the current recommendation object path
- add outcome tracking for the new recommendation-plan objects so backtesting and improvement stay first-class
- expose watchlist policy details more directly in the main operator workflows, not only through the policy endpoint
- decide whether sentiment snapshots become operator-facing compatibility artifacts, internal inputs, or candidates for retirement once context writers mature

## Phase 5: Expansion (only after the above)

Lower-priority growth items:
- additional provider integrations where they demonstrably improve signal quality
- historical exports and reporting helpers
- retry/dead-letter behavior for transient external failures
- selective service extraction only if scale demands it

## Roadmap discipline

A useful roadmap should separate three things clearly:
- what is shipped
- what is incomplete but necessary
- what is merely possible later

The project had started to blur those categories in a few docs. This roadmap keeps them separate so the near-term priority stays clear: finish reliability/security/observability hardening, then wire the redesign onto a real execution path before broadening feature scope.

## Related docs
- `architecture.md`: system design and component boundaries
- `getting-started.md`: setup and local development guide
- `features-and-capabilities.md`: current product behavior and limits
- `phase-2-app-native.md`: self-contained pipeline goals and remaining gaps
- `raw-details-reference.md`: stored diagnostics and payload reference
