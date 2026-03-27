# Roadmap

## Current status

Trade Proposer App now executes its critical workflows entirely inside this repository:
- **Persistent state**: watchlists, jobs, runs, settings, sentiment snapshots, redesign-native context/signal objects, recommendation plans, and recommendation-plan outcomes live in one schema and remain queryable from the UI or API.
- **Operator UI**: the React/Vite SPA provides dashboard, jobs, debugger, settings, docs, ticker, sentiment, ticker-signal, and recommendation-plan pages for the core operator workflows.
- **Execution model**: the worker-backed queue persists job metadata, honors concurrency controls, and logs timing/diagnostic payloads for reproducibility.
- **Feature-rich diagnostics**: every run emits structured `analysis_json`, feature vectors, aggregations, confidence weights, warnings, and workflow summaries.
- **Shared sentiment/context**: macro and industry refresh workflows persist reusable snapshots and transitional context objects, proposal generation links back to those artifacts, and health/preflight now reports snapshot freshness.
- **Signal integrity policy**: missing data becomes explicit neutral/warning output rather than an invented fallback.
- **Redesign write path**: watchlist orchestration, cheap-scan diagnostics, ticker signals, recommendation plans, recommendation-plan outcomes, event-ranked news-first macro/industry context writers, and a dedicated ticker deep-analysis service now exist inside the main app execution flow.
- **Legacy posture**: legacy recommendation operator surfaces are retired, optimization already uses recommendation-plan outcomes, the active product path no longer depends on legacy recommendation persistence, and the historical `recommendations` table is now dropped through migration `0015_drop_legacy_recommendations_table`.

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
- new redesign-backed proposal runs no longer emit legacy recommendation compatibility artifacts, and operator navigation now redirects retired recommendation-detail routes toward recommendation-plan-first workflows
- ticker drill-downs are being converged onto recommendation-plan/outcome history instead of legacy recommendation history
- mounted operator evaluation/history APIs are being narrowed toward recommendation-plan evaluation and away from legacy recommendation-history endpoints, with unused legacy history/detail UI code removed and evaluation-run summaries converged onto recommendation-plan outcome vocabulary
- ticker deep analysis now uses a redesign-native internal feature/context pipeline and only leans on legacy proposal services for raw data/news enrichment and compatibility fallback
- calibration reporting now includes horizon, transmission-bias, context-regime, and horizon-plus-setup-family slices so operators can judge where the redesign is or is not working, now marks slice sample quality explicitly, and watchlist-backed action gating now uses those richer slices with bounded sample-aware adjustments instead of relying only on setup family and confidence bucket

Current Phase 4 status:
- **Phase 4A** is complete: optimization, mounted operator flows, active proposal-run review, and legacy recommendation persistence retirement are all recommendation-plan/outcome-native, and the historical `recommendations` table is now explicitly dropped instead of being left as a hidden compatibility artifact
- **Phase 4B** is now substantially complete: setup-family-aware plan framing includes family-specific thesis/invalidation text, execution metadata, `no_action` reasoning, operator-visible evaluation focus, dedicated setup-family cohort reporting, family-specific evaluation review slices, and direct browse filtering by setup family
- **Phase 4C** is partially implemented: event-ranking/source-priority context writers, richer transmission diagnostics, a catalyst shortlist lane, and redesign-native ticker deep analysis are in place, but the context/transmission engine is still largely heuristic
- **Phase 4D** is meaningfully started but still early: stored outcomes, sample-aware calibration summaries, calibration-informed threshold gating, baseline cohort comparisons, and setup-family cohort review now exist, but confidence re-scaling and measured evidence concentration remain incomplete

Next required work in this phase:
- use the new calibration summaries to drive actual confidence re-scaling and operator thresholds rather than only reporting grouped outcomes
- continue maturing the redesign-native deep-analysis path from an internal native executor into a fuller ticker-signal / recommendation-engine layer with less dependence on legacy proposal payload shapes
- carry the completed Phase 4B setup-family framing/evaluation work forward into later phases without reopening generic plan behavior
- deepen macro/industry context extraction beyond heuristic saliency ranking into stronger event clustering, persistence/escalation, and contradiction handling
- continue cleaning residual wording or assumptions that still mention legacy recommendation storage after the explicit table drop
- decide whether sentiment snapshots become operator-facing compatibility artifacts, internal inputs, or candidates for retirement once context writers mature

Defined implementation phases from here:
1. **Phase 4A — optimization convergence and legacy deletion**
   - ✅ refactor optimization services, summaries, and tests to consume `RecommendationPlanOutcome`
   - ✅ remove remaining optimization dependence on legacy recommendation WIN/LOSS rows
   - ✅ stop proposal-run persistence, dashboard filtering, and mounted run-detail/debugger flows from depending on legacy recommendation rows/output payloads
   - ✅ delete dormant legacy recommendation ORM/repository persistence code from the active product path
   - ✅ continue narrowing API/UI/docs wording so recommendation-plan outcomes are the only active optimization truth source
   - ✅ drop the historical `recommendations` table through migration `0015_drop_legacy_recommendations_table`
   - status: complete
2. **Phase 4B — setup-family-native recommendation behavior**
   - ✅ strengthen family-specific thesis, invalidation, target, stop, timing expectation, and `no_action` generation
   - ✅ surface family-specific execution metadata and evaluation focus directly in operator review views
   - ✅ add deeper family-specific evaluation cohorts/reporting beyond the current shared calibration slices
   - ✅ add operator-facing setup-family review slices plus direct browse filtering by setup family
   - status: treat Phase 4B as substantially complete and fold further family refinements into Phase 4C/4D only when they are evidence-driven rather than cosmetic
3. **Phase 4C — richer context and transmission engine**
   - improve macro/industry event clustering and deduplication
   - track persistence vs escalation vs fade more explicitly
   - make transmission effects more measurable inside recommendation ranking, not just inspectable in diagnostics
4. **Phase 4D — calibration and evidence concentration**
   - move from grouped reporting toward cautious confidence re-scaling and operator gating informed by plan-outcome evidence
   - expand operator-visible cohort review around setup family, horizon, transmission bias, and context regime
   - prefer measured cohort concentration over broad predictive claims

Recommended implementation order inside Phase 4:
1. Phase 4A — optimization convergence and legacy deletion
2. Phase 4B — setup-family-native recommendation behavior
3. Phase 4C — richer context and transmission engine
4. Phase 4D — calibration and evidence concentration

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
