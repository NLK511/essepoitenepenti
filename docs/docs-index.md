# Documentation Index

**Status:** canonical navigation guide

This index shows where to start and what each doc is for.

It separates current product docs, technical reference, and archived history so the main reading path stays clear.

## Start here

If you are new to the repo or the app, read these first:

- `../README.md`
  - repo-level overview and quick start
- `getting-started.md`
  - local setup, startup, auth basics, first-run checks
- `operator-page-field-guide.md`
  - what each major UI page is for and how to use it
- `glossary.md`
  - shared vocabulary across runs, signals, plans, outcomes, and snapshots

## Canonical current-state docs

These docs define the current product truth.

### Product direction
- `product-thesis.md`
  - core goal
  - governing principle
  - strategic priority order
  - standard for future decisions

### Current product behavior
- `features-and-capabilities.md`
  - what operators can do now
  - current strengths
  - current weaknesses

### Recommendation logic
- `recommendation-methodology.md`
  - how the app-native scoring and planning pipeline works
  - context and support-snapshot layers
  - scoring and risk logic
  - methodology limits

### Current architecture
- `architecture.md`
  - runtime model
  - module boundaries
  - workflow topology
  - operational risks and next moves

### Active implementation tracking
- `ontology-enrichment-plan.md`
  - planned expansion of ticker, industry, and relationship coverage
  - tracking page for ontology work progress
  - guidance for validation, reporting, and split file structure
- `historical-replay-backtesting-plan.md`
  - phased plan for building a point-in-time historical replay dataset
  - rules for strict vs research backtests
  - guidance for context, news, and social-data feasibility

### Setup and operations
- `getting-started.md`
  - installation
  - startup
  - authentication basics
  - first-run troubleshooting
  - validation commands
  - optional Postgres integration-test workflow
- `default-watchlists.md`
  - seeded default watchlist strategy
  - universe construction rationale
  - compact naming and schedule rationale

### Current roadmap
- `roadmap.md`
  - what is clearly shipped now
  - what is still active work
  - what is explicitly later

### User workflow framing
- `user-journeys.md`
  - current intended operator journeys
  - deferred journeys that should not drive near-term design

## Technical reference docs

These are useful after you already understand the product shape.

### Stored payloads and diagnostics
- `raw-details-reference.md`
  - field-level reference for structured payloads
  - run artifacts
  - shared context and transitional support-snapshot payloads
  - diagnostics and timing

### Database structure
- `er-model.md`
  - current entity-relationship diagram for the live app schema
  - main foreign-key links between watchlists, jobs, runs, snapshots, plans, and outcomes

### Redesign specs still useful as active reference
- `redesign/README.md`
  - overview of active redesign docs
- `redesign/principles.md`
  - redesign rules and trust constraints
- `redesign/target-architecture.md`
  - desired longer-shape design for context, exposure, ticker setup, and trade-plan construction
- `redesign/transmission-modeling-spec.md`
  - transmission rules for context → industry → ticker reasoning
- `redesign/calibration-governance-spec.md`
  - sample-aware calibration and threshold-governance rules
- `redesign/setup-family-playbook.md`
  - setup-family-specific plan construction expectations
- `redesign/data-model-and-persistence.md`
  - redesign persistence direction and entity framing

## Archive

Archived docs are still valuable for future development and historical context, but they are not part of the main reading path.

Start with:
- `archive/README.md`
- `archive/roadmap-history.md`

Archived implementation/planning material includes:
- `archive/phase-2-app-native.md`
- `archive/implementation-plans/shared-sentiment-snapshot-implementation-plan.md`
- `archive/implementation-plans/shared-sentiment-snapshot-refactor.md`
- `archive/implementation-plans/nitter-social-implementation-checklist.md`
- `archive/implementation-plans/nitter-social-sentiment-design.md`
- `archive/redesign/migration-plan.md`
- `archive/redesign/implementation-charter.md`
- `archive/redesign/legacy-convergence-plan.md`
- `archive/redesign/measured-success-criteria.md`

## Maintenance rule

When a feature ships:
- update the canonical doc for that topic
- remove or archive planning language elsewhere
- do not leave shipped work described as major future work in multiple places

When a doc becomes mainly historical:
- move it to `docs/archive/`
- keep a short pointer from the active doc set if the history is still useful

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
