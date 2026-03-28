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
- Review persisted run timing, summary, artifact, and error details after execution finishes or fails.

### Recommendation workflow
- Persist proposal outputs as `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`.
- Store structured diagnostics beside those objects.
- Evaluate recommendation plans through the app-native price-history path.
- Review plans and outcomes through redesign-native pages instead of the old recommendation-history flow.
- Use ticker drill-down pages to review plan history and latest outcomes for a single name.

### Shared context workflow
- Persist shared macro and industry support snapshots plus redesign-native macro and industry context snapshots.
- Seed industry refresh from a richer taxonomy layer that now includes per-ticker profiles, explicit industry definitions, sector definitions, and first-pass relationship edges.
- Inspect recent context snapshots from the Context review page and open detail views for macro or industry context objects.
- Review stored industry ontology context in detail views, including sector, peer-industry framing, risk flags, and matched transmission edges.
- Store ticker-level relationship provenance in deep-analysis diagnostics so peer, supplier, and customer read-through is available in raw trade-review payloads.
- Surface matched ticker relationships on recommendation-review pages so operators can see supplier, customer, or peer read-through without opening raw JSON first.
- Use matched ticker relationships inside stored plan explanation text so operator-facing rationale and risk framing can reflect ticker-specific read-through when the current evidence supports it.
- Show dedicated ticker relationship read-through cards on key review pages so operators can inspect the matched peer / supplier / customer edges without digging into raw diagnostics.
- Normalize taxonomy themes and macro-channel values against governed registries so ontology consumers use a controlled vocabulary instead of only ad hoc free-form strings.
- Normalize transmission-channel values against a governed registry too, so ticker exposure and relationship channel fields move toward fully governed ontology values instead of drifting as free-form strings.
- Govern ontology relationship types and target kinds too, then derive structural edges like sector membership, macro-channel links, and theme exposure so more of the ontology graph uses controlled values instead of ad hoc strings.
- Keep deep-analysis transmission summaries closer to governed channel semantics by labeling exposure channels and avoiding the old habit of mixing theme or macro-sensitivity tags into channel lists.
- Govern transmission-summary tags, primary drivers, and conflict flags too, so operator review surfaces rely less on ad hoc strings and more on controlled summary semantics.
- Render governed labels for transmission tags, drivers, conflicts, and exposure channels on ticker-signal, recommendation-plan, and run-detail pages so operators can review readable summaries without opening raw JSON.
- Render governed transmission-channel labels on context snapshot detail pages too, including stored event rows and industry ontology profile channels.
- Use governed context-regime semantics in recommendation analytics slices too, so calibration and setup-family review cohorts rely less on duplicated ad hoc derivation.
- Govern transmission-bias analytics semantics too, and expose readable evidence-concentration slice labels so operator review surfaces rely less on raw backend keys.
- Carry readable analytics labels on stored latest-outcome payloads and calibration buckets too, so recommendation review pages can show governed bias/regime names instead of raw keys.
- Carry readable shortlist and calibration explanation labels too, including shortlist reason details, selection-lane labels, calibration review-status labels, and governed calibration reason details.
- Carry readable action-reason and contradiction-reason labels too, so recommendation-plan and context-detail pages rely less on raw internal codes.
- Queue macro and industry refresh workflows manually from the operator UI.
- Execute macro and industry refresh workflows asynchronously through the shared queued run path; immediate `run-now` endpoints still exist in the backend but are no longer the primary operator workflow.
- Trace which shared artifacts were used by a run or recommendation plan.
- See support-snapshot freshness in `/api/health` and `/api/health/preflight`; context objects are reviewable through the context APIs and UI.
- Optionally use Nitter as supporting social input for macro and industry context.

### Watchlist workflow
- Persist watchlists with metadata such as `description`, `region`, `exchange`, `timezone`, `default_horizon`, `allow_shorts`, and `optimize_evaluation_timing`.
- Seed a curated default watchlist pack through `scripts/deploy_watchlists.py`, covering 300 equities split across U.S., Europe, and Asia-Pacific continent-plus-macro-industry buckets; see `default-watchlists.md` for the rationale.
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
- persisted recommendation calibration, baseline, setup-family review, and evidence-concentration summaries derived from stored outcomes
- weight optimization inside the app
- shared support snapshots and context snapshots reused across runs
- operator-visible shortlist reasoning
- in-app docs and settings
- single-user bearer-token API protection plus encrypted provider credentials at rest

## Current limits

The main limits are still practical ones:
- scheduler and worker reliability still need more hardening, especially stale-run recovery after process death
- observability is still thin for a multi-process workflow app because logs are not yet structured and daemon liveness is not surfaced explicitly
- auth, RBAC, tenancy, and credential lifecycle are still incomplete; the current security model is single-user and frontend auth tokens are stored in local storage
- context extraction is still heuristic rather than a mature event model
- ticker deep analysis still reuses some older proposal-engine internals
- support snapshots are no longer the main review UX, but they still remain in refresh, resolver, and health paths as a transitional backend dependency
- confidence calibration is present, but it still needs more evidence over time

There is also one analytical limit:
- coherent output is not the same as measured edge

## See also

- `operator-page-field-guide.md` — where these workflows show up in the UI
- `recommendation-methodology.md` — how the pipeline works
- `raw-details-reference.md` — stored fields and payloads
- `roadmap.md` — current priorities
