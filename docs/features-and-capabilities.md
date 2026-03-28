# Features and Capabilities

**Status:** canonical current product behavior

This document answers one question:
> what can the app do today?

Trade Proposer App covers the main operator loop inside one product:
- define watchlists
- create and run jobs
- inspect ticker signals and recommendation plans
- review degraded runs and missing inputs
- evaluate outcomes later
- refresh shared context
- adjust settings without leaving the app

The product is currently a short-horizon analysis and trade-planning tool. It helps rank names, frame trades, and keep an audit trail. It is not yet a proven short-horizon prediction engine.

## What operators can do now

### Workflow operations
- Create, edit, delete, and execute jobs.
- Run proposal generation, recommendation evaluation, weight optimization, and macro/industry context refresh jobs through the same run system.
- Convert proposal jobs into watchlists and schedule them.
- Inspect queued, running, completed, failed, cancelled, and warning-heavy runs from the debugger and run detail pages.

### Recommendation workflow
- Persist proposal outputs as `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`.
- Store structured diagnostics beside those objects.
- Evaluate recommendation plans through the app-native price-history path.
- Review plans and outcomes through redesign-native pages instead of the old recommendation-history flow.
- Use ticker drill-down pages to review plan history and latest outcomes for a single name.

### Shared context workflow
- Persist shared macro and industry support snapshots plus redesign-native macro and industry context snapshots.
- Inspect recent context snapshots from the Context review page and open detail views for macro or industry context objects.
- Queue or run macro and industry refresh workflows manually.
- Trace which shared artifacts were used by a run or recommendation plan.
- See support-snapshot freshness in `/api/health` and `/api/health/preflight`; context objects are reviewable through the context APIs and UI.
- Optionally use Nitter as supporting social input for macro and industry context.

### Watchlist workflow
- Persist watchlists with metadata such as `description`, `region`, `exchange`, `timezone`, `default_horizon`, `allow_shorts`, and `optimize_evaluation_timing`.
- Inspect watchlist policy and timing assumptions through the API and UI.
- Run watchlist-backed proposal jobs through a staged flow:
  1. cheap scan across the watchlist
  2. shortlist selection
  3. deep analysis for shortlisted names
  4. persistence of signals and plans
- Browse ticker signals and recommendation plans outside the run page.
- Filter redesign-native objects by `run_id`.
- Review shortlist rules, rejection counts, shortlist decisions, transmission fields, and warnings in operator views.
- Queue recommendation-plan evaluation runs from the recommendation-plans page.

### Diagnostics and docs
- Inspect structured `analysis_json` sections in the UI.
- Review news coverage, support/context coverage, feature vectors, aggregations, weights, warnings, and timing metadata.
- Browse markdown docs in-app.
- Configure summarization and providers from the settings page.

## What is in place

These parts of the product are already in place and connected:
- proposal creation and execution
- auditable run persistence
- redesign-native signal and plan storage
- recommendation-plan outcome evaluation
- weight optimization inside the app
- shared support snapshots and context snapshots reused across runs
- operator-visible shortlist reasoning
- in-app docs and settings

## Current limits

The main limits are still practical ones:
- scheduler and worker reliability still need more hardening
- observability is still thin for a multi-process workflow app
- auth, RBAC, tenancy, and credential lifecycle are still incomplete
- context extraction is still heuristic rather than a mature event model
- ticker deep analysis still reuses some older proposal-engine internals
- confidence calibration is present, but it still needs more evidence over time

There is also one analytical limit:
- coherent output is not the same as measured edge

## See also

- `operator-page-field-guide.md` — where these workflows show up in the UI
- `recommendation-methodology.md` — how the pipeline works
- `raw-details-reference.md` — stored fields and payloads
- `roadmap.md` — current priorities
