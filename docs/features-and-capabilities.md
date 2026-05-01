# Features and Capabilities

**Status:** canonical current product behavior

This document answers one question:
> what can the app do today?

It is a current-state reference, not a roadmap.

Trade Proposer App is a short-horizon analysis and trade-planning tool. It helps operators:
- define watchlists
- run proposal, evaluation, tuning, and context-refresh jobs
- review candidates, action plans, and outcomes
- review shared context when the broader backdrop matters
- adjust settings and providers inside the app

It is not yet a proven short-horizon prediction engine.

## Current capabilities

### Jobs, runs, and operations
- Create, edit, delete, schedule, and execute jobs.
- Run proposal generation, recommendation evaluation, plan-generation tuning, and macro/industry refreshes through the same worker-backed run system.
- Bars-data-refresh runs retry unresolved ticker fetches a bounded number of times, persist per-ticker retry diagnostics in the run artifact, and finish with warnings instead of aborting the whole run when some tickers still fail.
- Regional bars-data-refresh jobs resolve their tickers from the current seeded regional watchlists at runtime, so bars recovery stays in sync when the watchlist pack is updated.
- Inspect queued, running, completed, failed, canceled, and warning-heavy runs in the debugger and run detail pages.
- Review persisted run timing, summaries, artifacts, warnings, and failure metadata.
- Delete individual runs from the debugger.

### Recommendations and review
- Persist proposal outputs as `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`.
- Review signals, plans, and outcomes through the main review pages.
- Evaluate recommendation plans through the app-native price-history path, including terminal `expired` handling once a plan passes its intended horizon without a win/loss resolution.
- Track **phantom trades** for `no_action` or `watchlist` plans that retain an intended direction and valid trade levels, evaluating them against real market data to produce outcomes such as `phantom_win`, `phantom_loss`, or `phantom_no_entry` for recall optimization in tuning engines.
- Automatically submit actionable `long`/`short` plans to Alpaca paper trading using the Settings-configured notional cap per plan (default $1,000), limit bracket orders, and persisted broker-order records.
- Periodically reconcile open broker orders against Alpaca during market hours so fulfilled or canceled orders show up in the app without waiting for a manual action.
- Maintain a broker-position lifecycle ledger for app-submitted Alpaca bracket orders, including submitted/open/win/loss states, entry/exit fills, realized P&L, return percentage, and R multiple when the latest broker snapshot contains enough data.
- Block new broker submissions through a broker-backed risk manager when the manual kill switch is active or daily loss, open exposure, same-ticker, single-position, or loss-streak limits are breached.
- Show broker-backed dashboard performance statistics, including closed broker positions, broker win rate, realized P&L, and manual/periodic dashboard refresh, so live paper-trading performance is visible even when simulated outcome calibration is thin.
- When a plan has live Alpaca execution data, operator-facing plan views treat broker evaluation as the primary status and keep the simulated plan outcome as secondary context.
- Inspect broker-order submissions, payloads, statuses, linked position lifecycle state, realized P&L, and re-submit/cancel/refresh controls through the Broker Orders page and the broker-orders panel on run detail.
- Run detail now includes the broker-order history for that run so operators can audit execution without switching pages.
- Use decision samples to review near-misses, shortlist behavior, triage priority, and richer filters such as shortlist state, setup family, transmission bias, context regime, and benchmark result.
- Run signal-gating tuning through its dedicated research workflow to inspect shortlist recall and calibration-related review surfaces.
- Use the calibration report endpoint and the research-page calibration tab to inspect confidence reliability, Brier score, and expected calibration error.
- Use ticker drill-down pages to inspect plan history and latest outcomes for a single name.

### Shared context and ontology
- Persist macro and industry context snapshots as the canonical shared-context artifacts.
- Review macro and industry context from the Context pages and detail views.
- **Realistic Context Reconstruction:** Re-generate historical context snapshots from past news and social data. For time-windowed company/ticker news requests, the app now prefers Finnhub and rejects undated or future-dated articles so historical simulations do not silently mix in later company news.
- Store context-event fields such as persistence state, state transition, catalyst type, market interpretation, trigger actor, trigger actor role, trigger source type, and short "why now" summaries.
- Trace which shared artifacts were used by a run or recommendation plan.
- Use the taxonomy layer for industry definitions, sector definitions, ticker profiles, relationship edges, and governed parent/child lineage for macro and theme vocabularies.
- Transmission edges are now treated as typed graph entries with direction, mechanism, confidence, provenance, and optional point-in-time validity semantics.
- Provider-backed taxonomy enrichment now promotes specific industry labels from market metadata where available and fills missing domiciles from the same source instead of guessing.
- The seeded 750-ticker default watchlist universe is now explicitly represented in the ontology, so default-region coverage no longer depends on sector fallback alone.
- Expand industry refresh queries from ontology context such as industry queries, themes, event vocabulary, risk flags, sector, known company names, and governed ancestor labels when they improve recall.
- Surface ticker relationship read-throughs such as peer, supplier, and customer links in review pages and stored diagnostics.
- Use governed labels for transmission, calibration, outcome, and event metadata so UI pages do not depend on raw internal keys.
- Optionally use Nitter as supporting social input for macro and industry context.

### Watchlists and proposal flow
- Persist watchlists with metadata such as region, exchange, timezone, default horizon, and shorting policy.
- Seed the curated default watchlist pack with `scripts/deploy_watchlists.py`; see `default-watchlists.md` for rationale.
- Reconstruct historical macro and industry context using `scripts/reconstruct_context.py` with a NewsAPI credential when the shared-context tables need to be backfilled.
- Historical ticker/company news requests prefer Finnhub when a time window is supplied; unsafe live-feed fallbacks are skipped instead of leaking future company articles into replay.
- Run watchlist-backed proposal jobs through a staged flow:
  1. watchlist scan
  2. shortlist selection
  3. deep analysis for shortlisted names only
  4. persistence of signals for all scanned names, decision samples for audit/tuning, and plans only when downstream plan framing actually ran; cheap-scan-only rejected names stay as signal-plus-decision-sample evidence, while phantom-trade-eligible rejected plans are reserved for shortlisted names that reached real trade framing but still ended as `no_action` or `watchlist`
- **Hybrid Market Data Fetching:** Cheap scan prefers local database bars (including 1m-to-daily resampling), retries transient remote failures, and still scores the ticker from local data when local history is sufficient. Deep analysis prefers fresh remote bars in live runs, retries transient remote failures, and falls back to persisted local bars before surfacing deep analysis as unavailable.
- **Relative-strength and volume-confirmation features:** ticker deep analysis now computes short and medium lookback relative returns versus `SPY` and a sector ETF proxy when available, plus simple `volume_ratio_20` and `dollar_volume_ratio_20` confirmation features. Missing benchmark or sector data degrades to neutral diagnostics instead of aborting the run.
- **Market-Data Diagnostics In Details:** cheap-scan and deep-analysis fetch diagnostics are stored in signal details, plan details, and run/job artifact details. They are intentionally not added to compact summary rows.
- **Lazy Hydration:** Remote Yahoo bars fetched for cheap scan or deep analysis are persisted back to the local database when possible to accelerate future runs.
- Browse signals and plans outside the run page and filter them by `run_id`.
- Queue recommendation-plan evaluation runs from the recommendation-plans page.

### Diagnostics, settings, and docs
- Inspect structured `analysis_json` payloads in the UI when deeper debugging is needed.
- Review warnings, timing, calibration summaries, and other diagnostics through detail pages and advanced review surfaces.
- Configure summarization, providers, and ingestion from Settings. Provider secrets are write-only in the UI and are not returned by the settings API.
- Browse the project markdown docs in-app.

## What is already in place

The shipped baseline includes:
- watchlists, jobs, runs, settings, docs browsing, and audit history
- signal and decision-sample persistence for scanned names, plus plan and outcome persistence for names that reached downstream plan framing
- recommendation-plan evaluation and advanced review analytics
- signal-gating tuning and plan-generation tuning inside the app as research workflows
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
- strict historical macro/topic news is still limited on the free-provider stack because Finnhub free access is company-news oriented rather than broad topic search; in those cases the app now prefers missing evidence over unsafe future leakage
- calibration exists, but evidence remains limited

And one analytical caution still matters:
- coherent output is not the same as measured edge

## See also

- `operator-page-field-guide.md` — where these workflows show up in the UI
- `recommendation-methodology.md` — how the pipeline works
- `bars-refresh-spec.md` — canonical bars-data-refresh run behavior
- `news-provider-reliability-spec.md` — canonical ticker-news retry and fallback diagnostics behavior
- `raw-details-reference.md` — stored fields and payloads
- `roadmap.md` — current priorities
