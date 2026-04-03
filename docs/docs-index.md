# Documentation Index

**Status:** canonical navigation guide

This index keeps the current reading path short.

Use it to answer two questions:
- where should I start?
- which docs are current reference vs planning vs archive?

## Start here

If you are new to the repo, read these first:
- `../README.md` — repo overview and quick start
- `getting-started.md` — setup, startup, auth basics, troubleshooting
- `operator-page-field-guide.md` — main UI pages and operator flow
- `glossary.md` — shared terms used across the app

## Canonical current-state docs

These define the current product truth.

### Product and behavior
- `product-thesis.md` — product goal, decision rules, and priority order
- `features-and-capabilities.md` — what the app does today and its current limits
- `roadmap.md` — active priorities only
- `user-journeys.md` — intended operator journeys

### Setup and operations
- `getting-started.md` — local setup, scripts, auth, validation, first-run checks
- `default-watchlists.md` — seeded watchlist pack and rationale

### Recommendation workflow
- `recommendation-methodology.md` — current scoring and planning pipeline
- `recommendation-plan-resolution-spec.md` — canonical plan outcome semantics
- `recommendation-plan-evaluation-recompute-notes.md` — evaluator edge cases and recompute notes
- `decision-sample-tuning-guide.md` — how to review and tune decision samples

### Architecture and data
- `architecture.md` — runtime model and module boundaries
- `raw-details-reference.md` — stored payload and diagnostics reference
- `er-model.md` — current schema overview

## Active implementation and research docs

These are useful, but they are not the main current-state entry point.

- `ontology-enrichment-plan.md` — active ontology/taxonomy work
- `historical-replay-backtesting-plan.md` — target shape for historical replay
- `historical-replay-implementation-checklist.md` — codebase-specific replay checklist
- `signal-gating-tuning-plan.md` — development tuning workflow for signal gating
- `plan-generation-tuning-spec.md` — authoritative implementation spec for autonomous plan-generation tuning
- `plan-generation-tuning-implementation-plan.md` — concrete codebase implementation plan and replacement strategy
- `ui-decluttering-plan.md` — active UI cleanup plan
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

### Product understanding
- `product-thesis.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `roadmap.md`

### Technical reference
- `architecture.md`
- `raw-details-reference.md`
- `redesign/README.md`
