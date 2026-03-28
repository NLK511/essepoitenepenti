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
- watchlists, jobs, runs, settings, sentiment snapshots, ticker signals, recommendation plans, and recommendation-plan outcomes all persist inside one app-owned schema
- the React/Vite operator UI supports dashboard, watchlists, jobs, debugger, run detail, context snapshots, ticker signals, recommendation plans, ticker drill-down, settings, and docs browsing
- proposal generation, evaluation, optimization, and context refresh all execute inside this repository through the worker-backed run system
- recommendation review is now centered on redesign-native objects: `TickerSignalSnapshot`, `RecommendationPlan`, and `RecommendationPlanOutcome`
- health and preflight surface degraded dependencies and snapshot freshness rather than hiding them
- optimization already uses redesign-native outcomes rather than legacy recommendation history

## Active priorities

## 1. Reliability
Highest current priority.

Still needed:
- stronger overlap handling and crash recovery for scheduler/worker execution
- clearer recovery semantics when partial failures occur
- better coordination guarantees if concurrency increases

## 2. Observability
The product is now feature-complete enough that runtime clarity matters more than additional surface area.

Still needed:
- structured logs and run correlation
- clearer production-facing health signals
- worker and scheduler heartbeats or equivalent operational visibility
- easier diagnosis of provider failures and degraded states across processes

## 3. Security and credential lifecycle
The app should not expand provider surface area faster than it improves secret handling.

Still needed:
- stronger single-user auth hardening
- clearer credential rotation and re-encryption workflow
- optional external secret-backend support if deployment needs justify it

## 4. Measured recommendation quality
The redesign path now has enough persistence and review plumbing that the next question is evidence quality, not raw feature quantity.

Still needed:
- accumulate more resolved recommendation-plan outcomes over time
- use calibration summaries to improve operator trust and confidence discipline without creating false precision
- keep comparing actual trade-plan behavior against simple baseline cohorts
- verify which setup families, horizons, transmission conditions, and regimes are actually working

## 5. Redesign maturation
The redesign is already the active product path, but it still needs deeper evidence and cleaner narrowing of transitional concepts.

Still needed:
- continue improving ticker-analysis quality without reopening generic legacy patterns
- decide the long-term role of sentiment snapshots now that richer context objects exist
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
