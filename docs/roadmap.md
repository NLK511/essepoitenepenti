# Roadmap

**Status:** active plan

This roadmap is intentionally short. It lists only current priorities and clearly deferred work. Shipped behavior belongs in `features-and-capabilities.md`; detailed history belongs in `archive/roadmap-history.md`.

## Current baseline

Trade Proposer App already has the core operator workflow in place:

- watchlists, jobs, runs, settings, context snapshots, ticker signals, recommendation plans, outcomes, broker orders, and broker positions persist in one schema
- proposal generation, evaluation, tuning, context refresh, paper execution, and broker reconciliation run inside this repository
- the UI supports review, quality, execution/risk, context, data-quality, run-debugging, settings, and in-app docs workflows
- health, preflight, warnings, provenance, run leases, worker heartbeats, and correlation ids make degraded state visible
- calibration, effective outcomes, walk-forward tuning, and baseline comparisons exist, but measured edge is still thin
- Alpaca paper execution is active; eToro read-only/demo/live-shadow plumbing exists; real eToro live mutation remains fail-closed

## Active priorities

Priority order follows `product-thesis.md`: reliability, observability, security, evidence quality, then feature expansion.

### 1. Reliability

- keep soaking worker/scheduler crash recovery, leases, stale-run recovery, and partial-persistence behavior
- strengthen coordination only if real concurrency pressure appears
- keep old persisted rows readable when status names or payload shapes evolve

### 2. Observability

- improve provider/broker lifecycle event presentation across API, worker, and scheduler processes
- make daemon health, stale broker snapshots, circuit breakers, and `needs_review` exposure easy to diagnose from the UI/API
- keep detailed artifacts on detail/research pages, not dashboard page-load paths

### 3. Security and credential lifecycle

- harden single-user auth defaults for production
- document and test credential rotation/re-encryption
- keep provider/broker secrets write-only and redacted in API, UI, logs, artifacts, and observability events
- consider external secret storage only if deployment needs justify it

### 4. Production readiness and live broker safety

- complete `production-readiness-plan.md`: production preflight, backup/restore proof, incident runbooks, staging soak, and operator sign-off
- require eToro read-only, demo, live-shadow, and release-readiness artifacts before any live-money implementation path
- keep broker halt, account-scoped limits, drawdown/circuit-breaker checks, and reconciliation evidence as non-negotiable gates

### 5. Measured recommendation quality

- accumulate more broker-backed and replay-backed outcomes
- compare against simple baselines, not only internal scores
- validate setup family, horizon, confidence bucket, market regime, ontology/transmission state, and fundamental-context slices
- keep thin calibration buckets and degraded-input penalties explicit
- promote tuning/config changes only after walk-forward, concentration, drawdown/loss-streak, and baseline checks

### 6. Redesign maturation

- keep `RecommendationPlan` review as the canonical operator decision path
- improve ticker-analysis quality without reviving duplicate legacy terms
- retire compatibility paths only after proving they are no longer used by migrations, tests, or old persisted rows

## Explicitly later

Lower priority until the active items above improve:

- more providers that mainly increase source count without measured quality gains
- broader automation beyond supervised operator workflows
- multi-user scope, RBAC, or tenancy before the single-user model is solid
- service extraction before scale or operational pressure requires it
- stronger predictive/profit claims before outcome history supports them

## Maintenance rule

If a feature ships, move stable behavior to the canonical current-state doc and remove it from this roadmap unless unfinished follow-through remains. Archive historical detail instead of leaving it in the main reading path.

## See also

- `product-thesis.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `architecture.md`
- `production-readiness-plan.md`
- `recommendation-quality-improvement-plan.md`
- `specs/historical-playback-tuning-spec.md`
- `archive/implementation-plans/historical-playback-tuning-operating-plan.md`
- `archive/roadmap-history.md`
