# Documentation Index

**Status:** canonical navigation guide

This index keeps the current reading path short.

Use it to answer two questions:
- where should I start?
- which docs are current reference vs planning vs archive?

## Start here

If you are new to the repo, read these first in order:
- `../README.md` — repo overview and quick start
- `getting-started.md` — setup, startup, auth basics, troubleshooting
- `operator-page-field-guide.md` — main UI pages, operator flow, and how to orient yourself in the product
- `glossary.md` — shared terms used across the app, including cohort, slice, bucket, and calibration language
- `recommendation-methodology.md` — the live recommendation path after you know the page and term basics

## Canonical current-state docs

These define the current product truth.

### Product and behavior
- `product-thesis.md` — product goal, decision rules, and priority order
- `features-and-capabilities.md` — what the app does today and its current limits
- `roadmap.md` — active priorities only
- `user-journeys.md` — intended operator journeys

### Setup and operations
- `getting-started.md` — local setup, scripts, auth, validation, first-run checks
- `operational-scripts-reference.md` — reference for maintenance, hydration, and compare tools
- `default-watchlists.md` — seeded watchlist pack and rationale

### Recommendation workflow
- `recommendation-methodology.md` — current scoring and planning pipeline
- `recommendation-plan-resolution-spec.md` — canonical plan outcome semantics
- `decision-sample-tuning-guide.md` — how to review and tune decision samples
- `signal-gating-benchmark-spec.md` — current decision-sample benchmark semantics used by gating review
- `signal-gating-tuning-guide.md` — current shipped signal-gating tuning workflow and calibration-related review surfaces

### Architecture and data
- `architecture.md` — runtime model and module boundaries
- `raw-details-reference.md` — stored payload and diagnostics reference
- `er-model.md` — current schema overview

## Active implementation and research docs

These are useful, but they are not the main current-state entry point.

- `recommendation-quality-improvement-plan.md` — working tracker for recommendation-quality, calibration, and validation improvements
- `signal-gating-tuning-guide.md` — current shipped signal-gating tuning workflow
- `plan-generation-tuning-spec.md` — authoritative implementation spec for autonomous plan-generation tuning
- `alpaca-paper-order-execution-spec.md` — first automated broker-execution spec for Alpaca paper trading, including audit UI and manual resubmit/cancel controls
- `broker-position-lifecycle-spec.md` — broker-backed position state and realized P&L ledger for app-submitted bracket orders
- `broker-risk-management-spec.md` — broker-backed pre-trade risk limits and manual kill switch
- `nitter-social-relevance-scoring.md` — current Nitter relevance-ranking behavior

## Redesign reference

These remain active technical reference docs:
- `redesign/README.md` — redesign doc map
- `redesign/principles.md` — redesign rules
- `redesign/target-architecture.md` — high-level redesign shape
- `redesign/transmission-modeling-spec.md` — context-to-ticker transmission rules
- `redesign/calibration-governance-spec.md` — outcome-aware calibration rules
- `redesign/setup-family-playbook.md` — setup-family expectations
- `redesign/data-model-and-persistence.md` — redesign persistence direction
- `redesign/short-horizon-recommendation-architecture.md` — combined redesign reference

## Archive

Archived docs are still useful for history, but they are not part of the main reading path.

Start with:
- `archive/README.md`
- `archive/roadmap-history.md`
- `archive/implementation-plans/signal-gating-tuning-plan.md` — historical development plan for signal gating tuning
- `archive/implementation-plans/plan-generation-tuning-implementation-plan.md` — archived implementation plan and replacement strategy
- `archive/implementation-plans/recommendation-plan-evaluation-recompute-notes.md` — archived evaluator edge cases and recompute notes
- `archive/implementation-plans/historical-replay-backtesting-plan.md` — archived historical replay research plan
- `archive/implementation-plans/historical-replay-implementation-checklist.md` — archived historical replay implementation checklist
- `archive/implementation-plans/ontology-enrichment-plan.md` — archived ontology expansion and governance plan
- `archive/implementation-plans/tech-debt-remediation-plan.md` — archived context-refresh cleanup and terminology convergence plan
- `archive/implementation-plans/ui-decluttering-plan.md` — archived UI decluttering execution plan

## Maintenance rule

When a feature ships:
- update the canonical doc for that topic
- remove or archive planning language elsewhere
- avoid describing shipped work as major future work in multiple places

When a doc becomes mostly historical:
- move it to `docs/archive/`
- keep only a short pointer from active docs if needed

## Suggested reading paths

### New operator
- `getting-started.md`
- `operator-page-field-guide.md`
- `glossary.md`
- `recommendation-methodology.md`

### Product understanding
- `product-thesis.md`
- `features-and-capabilities.md`
- `operator-page-field-guide.md`
- `glossary.md`
- `recommendation-methodology.md`
- `roadmap.md`

### Technical reference
- `architecture.md`
- `raw-details-reference.md`
- `redesign/README.md`
