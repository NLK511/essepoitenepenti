# Roadmap

**Status:** canonical current-priority roadmap

This roadmap is short on purpose.

It covers three things only:
- what is shipped now
- what still needs work
- what is clearly later

Anything already shipped should live in the current-state docs, not be re-described here as future work.

Detailed history is in `archive/roadmap-history.md`.

## Current shipped baseline

Trade Proposer App already has its core workflow in place:
- watchlists, jobs, runs, settings, context snapshots, ticker signals, recommendation plans, and outcomes all persist inside one schema
- the operator UI supports dashboard, watchlists, jobs, debugger, run detail, context review, ticker signals, recommendation plans, ticker drill-down, settings, and docs browsing
- proposal generation, evaluation, optimization, and macro/industry refresh runs all execute inside this repository through the worker-backed run system
- recommendation review is centered on `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`
- health and preflight surface degraded dependencies and freshness instead of hiding them
- optimization already uses redesign-native outcomes

## Active priorities

### 1. Reliability
Highest current priority.

Already in place:
- persisted `scheduled_for` slots with uniqueness guards
- atomic-enough run claiming for the current model
- duplicate-run protections on enqueue paths
- persisted run timing, status, error fields, and failure metadata
- worker heartbeats and run leases
- stale-run recovery when leases expire, with older timeout fallback still present in some paths

Still needed:
- clearer recovery semantics when a run fails after partial persistence
- stronger coordination guarantees if concurrency grows

### 2. Observability
Runtime clarity now matters more than more surface area.

Already in place:
- persisted run timing, summaries, artifacts, and errors
- health and preflight visibility for degraded state
- warnings and provenance on context and recommendation review pages
- persisted worker heartbeat data
- `/api/health` separation between service health, dependency health, worker health, scheduler health, run health, and context freshness
- lease-age, stale-running-run, worker-heartbeat-age, and scheduler-heartbeat diagnostics in `/api/health`
- worker and scheduler daemon logging

Still needed:
- richer structured logs and stronger cross-process run correlation
- easier diagnosis of provider failures across processes
- continued polish of health signal presentation and operator-facing diagnostics

### 3. Security and credential lifecycle
The app should not expand provider surface area faster than it improves secret handling.

Already in place:
- single-user bearer-token API protection with login
- encrypted provider credentials at rest

Still needed:
- stronger auth hardening
- credential rotation and re-encryption workflow
- safer production defaults and guidance
- optional external secret-backend support if needed

### 4. Measured recommendation quality
The next question is evidence quality, not raw feature count.

Already in place:
- persisted `RecommendationPlanOutcome` records
- calibration summaries, baseline cohorts, setup-family review, and evidence-concentration review from stored outcomes
- calibration-aware confidence and gating in the orchestration path

Still needed:
- more resolved outcomes over time
- continued use of calibration without overstating thin buckets
- continued comparison against simple baselines
- validation of which setup families, horizons, transmission conditions, and regimes actually work in live data

### 5. Redesign maturation
The redesign is already the active path.

Already in place:
- recommendation-plan review as the main operator-facing decision flow
- dedicated context review and detail pages
- support-snapshot UI and persistence have been retired from the active runtime path

Still needed:
- continued improvement of ticker-analysis quality
- continued avoidance of duplicate legacy-vs-redesign terminology

## Explicitly later
Lower priority until the active items above improve:
- additional providers that mainly increase source count without measured quality gains
- broader automation beyond current operator workflows
- multi-user scope, RBAC, or tenancy before the single-user model is stronger
- service extraction unless scale or operational pressure clearly justifies it
- stronger predictive claims before outcome history and calibration support them

## Maintenance rule
If a feature is shipped, describe it in the canonical product docs and remove it from the active roadmap unless unfinished follow-through remains.

If historical detail is still useful, move it to archive rather than leaving it in the main reading path.

## See also
- `product-thesis.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `architecture.md`
- `archive/roadmap-history.md`
