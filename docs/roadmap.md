# Roadmap

## Current status

Trade Proposer App now executes its critical workflows entirely inside this repository:
- **Persistent state**: watchlists, jobs, runs, recommendations, settings, and sentiment snapshots live in one schema and remain queryable from the UI or API.
- **Operator UI**: the React/Vite SPA provides dashboard, jobs, history, debugger, settings, docs, ticker, and sentiment pages for the core operator workflows.
- **Execution model**: the worker-backed queue persists job metadata, honors concurrency controls, and logs timing/diagnostic payloads for reproducibility.
- **Feature-rich diagnostics**: every run emits structured `analysis_json`, feature vectors, aggregations, confidence weights, warnings, and workflow summaries.
- **Shared sentiment context**: macro and industry refresh workflows persist reusable snapshots, proposal generation links back to those snapshots, and health/preflight now reports snapshot freshness.
- **Signal integrity policy**: missing data becomes explicit neutral/warning output rather than an invented fallback.
- **Redesign write path**: watchlist orchestration, cheap-scan diagnostics, ticker signals, recommendation plans, event-ranked news-first macro/industry context writers, and a dedicated ticker deep-analysis service now exist inside the main app execution flow.

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

Guiding principle for the rest of this phase:
- build the redesign first as a measurable decision-support and candidate-ranking system
- do not assume predictive success just because the outputs look coherent
- steer implementation by stored outcomes, calibration, and operator usefulness rather than by adding more unmeasured complexity

Delivered in this phase so far:
- first-class watchlist metadata aligned with trading horizons and exchange-aware scheduling
- watchlist policy inspection endpoints and operator-visible policy summaries in watchlist/run-detail workflows
- persisted redesign-domain models for:
  - macro context snapshots
  - industry context snapshots
  - ticker signal snapshots
  - recommendation plans
- repository and read API support for those new persisted objects
- real watchlist-backed cheap-scan → shortlist → deep-analysis orchestration
- dedicated cheap-scan signal model instead of recycled proposal confidence
- dedicated `TickerDeepAnalysisService` extraction so orchestration no longer calls `ProposalService` directly
- redesign-native `TickerDeepAnalysisService` execution path now computes ticker analysis internally instead of delegating normal watchlist deep analysis to `ProposalService.generate(...)`
- persistence of `TickerSignalSnapshot` and `RecommendationPlan` for every scanned watchlist ticker
- run-scoped API/UI visibility for redesign objects, including standalone browse pages for ticker signals and recommendation plans
- richer run artifacts that now record shortlist rules, rejection counts, and per-ticker shortlist decisions
- operator-facing shortlist reasoning surfaced more directly in run detail and ticker-signal views, including lane selection, catalyst proxy scores, and transmission context
- first-class `recommendation_outcomes` persistence for `RecommendationPlan`, including horizon returns, excursion metrics, direction correctness, confidence buckets, and setup-family capture
- app-native recommendation-plan evaluation flow exposed through API/UI queue actions and persisted back onto plans as latest outcomes
- setup-family-aware recommendation generation and decomposed confidence payloads now flow into watchlist-backed `RecommendationPlan` writes through `signal_breakdown` and `evidence_summary`
- recommendation-outcome calibration summaries now aggregate results by confidence bucket and setup family through API/UI operator workflows
- watchlist-backed recommendation plans now use those stored calibration slices to raise or relax action thresholds for underperforming or outperforming confidence/setup cohorts
- recommendation-plan workflows now expose baseline cohort comparisons so operators can compare actual actionable output against simple high-confidence, cheap-scan-attention, momentum-lane, and catalyst-lane slices
- watchlist orchestration now includes richer ticker transmission summaries, now carrying primary drivers, conflict flags, and expected transmission windows, plus a reserved catalyst/event shortlist lane so cheap-scan technical ranking does not own every deep-analysis slot
- recommendation-plan generation now carries setup-family-specific entry style and invalidation framing so plans differ more meaningfully across breakout / continuation / mean-reversion / catalyst-driven cases
- operator plan views now surface calibration slice reasons and sample quality more directly, while docs increasingly frame `RecommendationPlan` + outcome review as the redesign’s canonical operator truth path
- manual ticker proposal jobs now also execute through redesign orchestration via an explicit synthetic `1w` wrapper, reducing the remaining proposal-path gap between watchlist and manual workflows
- run-detail operator views now show when a proposal run came from manual tickers versus a real watchlist and explicitly mark redesign plans/outcomes as canonical
- new redesign-backed proposal runs no longer emit legacy recommendation compatibility artifacts, and operator navigation is being narrowed toward recommendation-plan-first workflows
- ticker drill-downs are being converged onto recommendation-plan/outcome history instead of legacy recommendation history
- ticker deep analysis now uses a redesign-native internal feature/context pipeline and only leans on legacy proposal services for raw data/news enrichment and compatibility fallback
- calibration reporting now includes horizon, transmission-bias, context-regime, and horizon-plus-setup-family slices so operators can judge where the redesign is or is not working, now marks slice sample quality explicitly, and watchlist-backed action gating now uses those richer slices with bounded sample-aware adjustments instead of relying only on setup family and confidence bucket

Next required work in this phase:
- use the new calibration summaries to drive actual confidence re-scaling and operator thresholds rather than only reporting grouped outcomes
- continue maturing the redesign-native deep-analysis path from an internal native executor into a fuller ticker-signal / recommendation-engine layer with less dependence on legacy proposal payload shapes
- lock the remaining redesign decision logic into explicit specs: transmission modeling, calibration governance, setup-family playbook, measured success criteria, and legacy convergence
- expose watchlist policy details more directly in the main operator workflows, not only through the policy endpoint
- define how the new recommendation-plan path coexists with or replaces the current recommendation object path
- decide whether sentiment snapshots become operator-facing compatibility artifacts, internal inputs, or candidates for retirement once context writers mature

Recommended implementation order inside Phase 4:
1. operator-facing watchlist policy visibility
2. deepen the redesign-native ticker-analysis engine beyond legacy proposal payload compatibility
3. calibration-informed confidence/threshold refinement
4. legacy-path narrowing and retirement decisions

## Phase 5: Expansion (only after the above)

Lower-priority growth items:
- additional provider integrations where they demonstrably improve measured signal quality rather than just increase source count
- historical exports and reporting helpers
- retry/dead-letter behavior for transient external failures
- selective service extraction only if scale demands it
- broader automation only after the recommendation-plan path shows credible, repeatable outcome quality

## Roadmap discipline

A useful roadmap should separate three things clearly:
- what is shipped
- what is incomplete but necessary
- what is merely possible later

The project had started to blur those categories in a few docs. This roadmap keeps them separate so the near-term priority stays clear: finish reliability/security/observability hardening, then push the redesign toward measurable recommendation quality before broadening feature scope.

## Related docs
- `architecture.md`: system design and component boundaries
- `getting-started.md`: setup and local development guide
- `features-and-capabilities.md`: current product behavior and limits
- `phase-2-app-native.md`: self-contained pipeline goals and remaining gaps
- `raw-details-reference.md`: stored diagnostics and payload reference
