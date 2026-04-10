# Features and Capabilities

**Status:** canonical current product behavior

This document answers one question:
> what can the app do today?

It is a current-state reference, not a roadmap.

Trade Proposer App is a short-horizon analysis and trade-planning tool. It helps operators:
- define watchlists
- run proposal, evaluation, tuning, and context-refresh jobs
- inspect signals, plans, outcomes, and degraded states
- review shared context and supporting diagnostics
- adjust settings and providers inside the app

It is not yet a proven short-horizon prediction engine.

## Current capabilities

### Jobs, runs, and operations
- Create, edit, delete, schedule, and execute jobs.
- Run proposal generation, recommendation evaluation, plan-generation tuning, and macro/industry refreshes through the same worker-backed run system.
- Inspect queued, running, completed, failed, cancelled, and warning-heavy runs in the debugger and run detail pages.
- Review persisted run timing, summaries, artifacts, warnings, and failure metadata.
- Delete individual runs from the debugger.

### Recommendations and review
- Persist proposal outputs as `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`.
- Review signals, plans, and outcomes through the main review pages.
- Evaluate recommendation plans through the app-native price-history path, including terminal `expired` handling once a plan passes its intended horizon without a win/loss resolution.
- Use decision samples to review near-misses, shortlist behavior, triage priority, and richer filters such as shortlist state, setup family, transmission bias, and context regime.
- Use the calibration report endpoint and the research-page calibration tab to inspect confidence reliability, Brier score, and expected calibration error.
- Use ticker drill-down pages to inspect plan history and latest outcomes for a single name.

### Shared context and ontology
- Persist macro and industry context snapshots as the canonical shared-context artifacts.
- Review macro and industry context from the Context pages and detail views.
- Store context-event fields such as persistence state, state transition, catalyst type, market interpretation, trigger actor, trigger actor role, trigger source type, and short "why now" summaries.
- Trace which shared artifacts were used by a run or recommendation plan.
- Use the taxonomy layer for industry definitions, sector definitions, ticker profiles, and relationship edges.
- Expand industry refresh queries from ontology context such as industry queries, themes, event vocabulary, risk flags, sector, and known company names.
- Surface ticker relationship read-throughs such as peer, supplier, and customer links in review pages and stored diagnostics.
- Use governed labels for transmission, calibration, outcome, and event metadata so UI pages do not depend on raw internal keys.
- Optionally use Nitter as supporting social input for macro and industry context.

### Watchlists and proposal flow
- Persist watchlists with metadata such as region, exchange, timezone, default horizon, and shorting policy.
- Seed the curated default watchlist pack with `scripts/deploy_watchlists.py`; see `default-watchlists.md` for rationale.
- Run watchlist-backed proposal jobs through a staged flow:
  1. watchlist scan
  2. shortlist selection
  3. deep analysis for shortlisted names
  4. persistence of signals and plans
- Browse signals and plans outside the run page and filter them by `run_id`.
- Queue recommendation-plan evaluation runs from the recommendation-plans page.

### Diagnostics, settings, and docs
- Inspect structured `analysis_json` payloads in the UI.
- Review coverage, feature vectors, weights, warnings, timing, calibration summaries, and other diagnostics.
- Configure summarization and providers from Settings.
- Browse the project markdown docs in-app.

## What is already in place

The shipped baseline includes:
- watchlists, jobs, runs, settings, docs browsing, and audit history
- signal, plan, and outcome persistence
- recommendation-plan evaluation and stored review analytics
- plan-generation tuning inside the app
- shared context reuse across runs
- operator-visible shortlist reasoning and degraded-state reporting
- single-user bearer-token API protection and encrypted provider credentials at rest

## Current limits

The main limits are still practical:
- reliability still needs more hardening around worker/scheduler crash recovery and partial-persistence edge cases
- observability is still thin for a multi-process app; logs are not yet structured enough and daemon health is not surfaced clearly enough
- auth, RBAC, tenancy, and credential lifecycle are still incomplete; the app remains single-user and the frontend stores the bearer token locally
- context extraction is stronger than before at capturing short-horizon state changes, but it is still heuristic rather than a mature event model
- ticker deep analysis still reuses some older proposal-engine internals
- context refresh and proposal-time context reuse are now context-native, but the deeper event model is still heuristic rather than fully mature
- calibration exists, but evidence remains limited

And one analytical caution still matters:
- coherent output is not the same as measured edge

## See also

- `operator-page-field-guide.md` — where these workflows show up in the UI
- `recommendation-methodology.md` — how the pipeline works
- `raw-details-reference.md` — stored fields and payloads
- `roadmap.md` — current priorities
