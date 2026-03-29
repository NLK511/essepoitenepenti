# Roadmap

**Status:** canonical current-priority roadmap

This roadmap is short on purpose.

It covers three things only:
- what is shipped now
- what still needs work
- what is clearly later

Detailed completed-phase history is in `archive/roadmap-history.md`.

## Current shipped baseline

Trade Proposer App already has its core workflow in place:
- watchlists, jobs, runs, settings, support snapshots, ticker signals, recommendation plans, and recommendation-plan outcomes all persist inside one app-owned schema
- the React/Vite operator UI supports dashboard, watchlists, jobs, debugger, run detail, context review, ticker signals, recommendation plans, ticker drill-down, settings, and docs browsing
- proposal generation, evaluation, optimization, and macro/industry refresh runs all execute inside this repository through the worker-backed run system
- recommendation review is now centered on redesign-native objects: `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`
- health and preflight surface degraded dependencies and snapshot freshness rather than hiding them
- optimization already uses redesign-native outcomes rather than legacy recommendation history

## Active priorities

## 1. Reliability
Highest current priority.

Foundations already in place:
- scheduled runs have a persisted `scheduled_for` slot and a database uniqueness guard on `(job_id, scheduled_for)`
- run claiming is atomic at the row-update level, so two workers should not both flip the same queued run to `running`
- enqueue paths already avoid obvious duplicate active runs for the same job, and weight optimization has an explicit single-active-run guard
- run timing, status, error fields, and failure-phase artifact metadata are persisted so failed executions are inspectable after the fact
- scheduler and worker entry paths now recover obviously stale `running` runs by failing them once they exceed the configured `started_at` timeout, which also unblocks fresh scheduled or manual reruns

Still needed:
- stronger crash recovery than the current coarse started-at timeout; there is still no heartbeat, lease renewal, or safe stale-run requeue path yet
- clearer recovery semantics when a run fails after partially persisting summary, artifact, or downstream objects
- stronger coordination guarantees if scheduler or worker concurrency increases beyond the current simple polling/claim model

## 2. Observability
The product is now feature-complete enough that runtime clarity matters more than additional surface area.

Foundations already in place:
- runs persist timing, summary, artifact, status, duration, and error payloads, and the operator UI can inspect them through run detail views
- health and preflight endpoints already surface dependency checks and degraded state instead of silently masking missing inputs
- context and recommendation review flows now expose warnings, provenance, and degraded summaries in the main UI

Still needed:
- structured logs and explicit run correlation across API, worker, and scheduler processes; current daemon logging is still mostly `print(...)`/traceback output
- clearer production-facing health signals that distinguish app health from refresh freshness and legacy support-snapshot status
- worker and scheduler heartbeats or equivalent operational visibility
- easier diagnosis of provider failures and degraded states across processes without relying on manual log inspection or per-run drill-down

## 3. Security and credential lifecycle
The app should not expand provider surface area faster than it improves secret handling.

Foundations already in place:
- API access is guarded by a single-user bearer-token middleware with a login endpoint for the operator UI
- provider credentials are encrypted at rest in the database using the app secret rather than stored as plaintext

Still needed:
- stronger single-user auth hardening; the current model is still shared-secret based and the frontend stores the bearer token in local storage
- clearer credential rotation and re-encryption workflow; changing the app secret currently changes the encryption key, but there is no built-in rekey path for existing provider credentials
- safer production defaults and deployment guidance so placeholder auth credentials and tokens are not acceptable long-term
- optional external secret-backend support if deployment needs justify it

## 4. Measured recommendation quality
The redesign path now has enough persistence and review plumbing that the next question is evidence quality, not raw feature quantity.

Foundations already in place:
- recommendation-plan evaluation persists first-class `RecommendationPlanOutcome` records rather than relying on ad hoc historical review
- the backend already computes calibration summaries, baseline cohorts, setup-family reviews, and evidence-concentration summaries from stored outcomes
- watchlist orchestration already consumes calibration summaries to adjust confidence and gating thresholds when enough evidence exists

Still needed:
- accumulate more resolved recommendation-plan outcomes over time; most of the measurement logic is in place, but sample size remains the limiting factor
- keep using calibration summaries to improve operator trust and confidence discipline without overstating thin buckets
- keep comparing actual trade-plan behavior against simple baseline cohorts and prune baselines that are no longer informative
- verify which setup families, horizons, transmission conditions, and regimes are actually working in live accumulated data, not just in the scoring design

## 5. Redesign maturation
The redesign is already the active product path, but it still needs deeper evidence and cleaner narrowing of transitional concepts.

Foundations already in place:
- recommendation-plan review is the main operator-facing decision workflow
- context snapshots now have dedicated review/detail flows, clearer macro-vs-industry navigation, and explicit industry selection
- operator-facing support-snapshot UI has already been removed from the main review flow

Still needed:
- continue improving ticker-analysis quality without reopening generic legacy patterns
- continue retiring the legacy support-snapshot dependency in backend flow:
  - macro/industry refresh jobs still create support snapshots first and derive context snapshots from them
  - proposal and ticker-context resolution still depend on `SupportSnapshotResolver`, which blends legacy support data with newer context data
  - health and freshness reporting still treat support snapshots as a primary operational artifact
  - remove the remaining support-snapshot dependency from refresh, health, and scoring paths so the legacy layer can be deleted cleanly
- keep recommendation-plan review as the clear canonical workflow
- avoid reintroducing duplicate legacy-vs-redesign terminology

## Explicitly later
These are lower-priority until the active priorities above improve:
- additional providers that mainly increase source count without measured quality gains
- broader automation beyond current operator workflows
- multi-user scope, RBAC, or tenancy before the single-user model is operationally stronger
- service extraction unless scale or operational pressure clearly justifies it
- expansion of predictive claims before outcome history and calibration support them

## Maintenance rule
If a feature is shipped, describe it in the canonical product docs and remove it from the active roadmap unless unfinished follow-through remains.

If a detailed historical record is still useful, move it to archive rather than leaving it in the main reading path.

## See also
- `product-thesis.md` — product intent and decision rules
- `features-and-capabilities.md` — current behavior
- `recommendation-methodology.md` — current pipeline logic
- `architecture.md` — current system structure
- `archive/roadmap-history.md` — detailed historical roadmap record
