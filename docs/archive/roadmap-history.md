# Roadmap History

**Status:** archival historical roadmap detail

This document preserves roadmap detail that was removed from the active `../roadmap.md` so the main roadmap can stay focused on current priorities.

Use this document for:
- historical context on completed or substantially completed phases
- understanding how the redesign converged onto recommendation-plan-native workflows
- tracing previously shipped roadmap items without keeping them in the active reading path

Do not use this file as the canonical statement of current priorities.

## Historical summary

Trade Proposer App reached its current product shape through five broad phases:

1. operational hardening foundations
2. self-contained app-native intelligence
3. security and production-readiness framing
4. redesign execution-path convergence
5. later expansion topics

The sections below preserve the historically important shipped detail.

## Phase 1 history: operational hardening foundations

Delivered or largely delivered during this phase:
- scheduler-backed queueing and atomic claiming
- structured pipeline contracts and stored diagnostics
- worker-visible warning and failure categories
- preflight guardrails for core dependencies and snapshot freshness

Open items that remained after this phase and still matter today:
- stronger overlap and crash-recovery semantics
- clearer production health signals and structured logging
- tighter concurrency guarantees if multiple workers/processes are introduced

## Phase 2 history: self-contained app-native intelligence

Delivered:
- app-native proposal generation
- app-native evaluation
- app-native weight optimization
- configurable summarization via digest/OpenAI/Pi CLI
- structured diagnostics surfaced in the UI
- shared macro and industry sentiment snapshots reused during proposal generation

Open questions left behind by this phase:
- whether the expanded sentiment stack measurably improves outcomes
- how far sentiment sources should expand before evidence quality catches up
- how aggressively transitional snapshot-first concepts should remain operator-facing

## Phase 3 history: security and production-readiness framing

This phase mainly clarified priority rather than fully completing implementation.

Historically identified high-value work:
- credential lifecycle work
- single-user authentication hardening
- structured logging and run correlation
- worker/scheduler operational visibility

## Phase 4 history: redesign execution-path convergence

This was the largest product phase and the most important historical cleanup to preserve.

### What converged during Phase 4

Delivered across the redesign path:
- first-class watchlist metadata aligned with trading horizons and exchange-aware scheduling
- watchlist policy inspection endpoints and operator-visible policy summaries
- persisted redesign-domain models for macro context snapshots, industry context snapshots, ticker signal snapshots, recommendation plans, and recommendation outcomes
- repository and read-API support for those redesign-native objects
- real watchlist-backed cheap-scan → shortlist → deep-analysis orchestration
- dedicated cheap-scan signal model instead of recycled proposal confidence
- dedicated `TickerDeepAnalysisService` extraction and later redesign-native execution path
- persistence of `TickerSignalSnapshot` and `RecommendationPlan` for every scanned watchlist ticker
- run-scoped API/UI visibility for redesign objects, including standalone browse pages for ticker signals and recommendation plans
- richer run artifacts with shortlist rules, rejection counts, and per-ticker shortlist decisions
- operator-facing shortlist reasoning in run detail and ticker-signal views
- first-class `recommendation_outcomes` persistence for `RecommendationPlan`
- app-native recommendation-plan evaluation flow through API/UI queue actions
- setup-family-aware recommendation generation and decomposed confidence payloads
- recommendation-outcome calibration summaries by confidence bucket and setup family
- baseline cohort comparisons for actionable output vs simpler heuristic cohorts
- richer transmission summaries, conflict flags, expected windows, and catalyst/event lanes
- setup-family-specific entry, invalidation, target, timing, and evaluation framing
- manual ticker proposal jobs routed through redesign orchestration using a synthetic wrapper
- ticker drill-downs converged onto recommendation-plan/outcome history rather than legacy recommendation history
- mounted operator evaluation/history APIs narrowed toward recommendation-plan evaluation
- calibration reporting expanded to horizon, transmission-bias, context-regime, and horizon-plus-setup-family slices
- historical `recommendations` table dropped through migration `0015_drop_legacy_recommendations_table`

### Historical Phase 4A summary — optimization convergence and legacy deletion

Historically completed:
- optimization services moved to `RecommendationPlanOutcome`
- remaining optimization dependence on legacy recommendation WIN/LOSS rows removed
- proposal-run persistence and review flows no longer depended on legacy recommendation rows
- dormant legacy recommendation persistence code removed from the active product path
- active wording and workflows narrowed toward recommendation-plan outcomes as the only optimization truth source
- historical `recommendations` table explicitly dropped

### Historical Phase 4B summary — setup-family-native recommendation behavior

Historically delivered:
- stronger family-specific thesis, invalidation, target, stop, timing expectation, and `no_action` generation
- family-specific execution metadata and evaluation focus in operator review views
- deeper family-specific evaluation cohorts and reporting
- operator-facing setup-family review slices and direct browse filtering by setup family

### Historical Phase 4C summary — richer context and transmission engine

Historically delivered:
- improved macro/industry event clustering and deduplication
- more explicit persistence vs escalation vs fade lifecycle state
- contradictory-event detection and lifecycle summaries in context metadata
- redesign-native context lifecycle/event metadata fed back into ticker analysis
- transmission effects made more measurable in ranking and action gating

### Historical Phase 4D summary — calibration and evidence concentration

Historically delivered:
- movement from grouped reporting toward cautious confidence re-scaling and operator gating informed by plan outcomes
- operator-visible cohort review around setup family, horizon, transmission bias, and context regime
- evidence-concentration reporting for strongest and weakest measurable cohorts

### Historical takeaway from Phase 4

By the end of this convergence work, the redesign path had become the active operator truth path. The remaining limitation was no longer missing plumbing; it was evidence accumulation over time.

## Phase 5 history: later expansion bucket

Historically identified as intentionally later:
- additional providers where they demonstrably improve measured signal quality
- historical exports and reporting helpers
- retry/dead-letter behavior for transient failures
- selective service extraction only if scale demands it
- broader automation only after recommendation-plan quality shows credible repeatability

## Historical roadmap discipline rule

A useful roadmap should separate:
- what is shipped
- what is incomplete but necessary
- what is only possible later

This history file exists because the active roadmap had accumulated too much shipped detail. The current docs should prefer a short active roadmap plus archival history, rather than mixing both into one file.

## Related archived docs
- `redesign/migration-plan.md`
- `redesign/implementation-charter.md`
- `redesign/legacy-convergence-plan.md`
- `redesign/measured-success-criteria.md`
