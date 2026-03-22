# Documentation Index

This page explains which document is canonical for which topic so the documentation stays consistent and easy to maintain.

## Canonical docs

### Product direction
- `product-thesis.md`
  - core goal
  - governing principle
  - strategic priorities
  - decision standard for future work

### Current architecture
- `architecture.md`
  - runtime model
  - module boundaries
  - workflow topology
  - architectural risks and next moves

### Current product behavior
- `features-and-capabilities.md`
  - what operators can do now
  - current strengths
  - current weaknesses

### Setup and operations
- `getting-started.md`
  - local setup
  - startup
  - auth basics
  - common first-run issues

### Recommendation logic
- `recommendation-methodology.md`
  - how the scoring pipeline works
  - sentiment layers
  - scoring and risk logic
  - methodology limits

### Stored payloads and diagnostics
- `raw-details-reference.md`
  - field-level reference for structured payloads
  - run artifacts
  - sentiment snapshots
  - diagnostics and timing

### Roadmap
- `roadmap.md`
  - what is shipped
  - what is incomplete but necessary
  - what is intentionally later

### User-facing workflow framing
- `user-journeys.md`
  - current operator journeys
  - deferred journeys that should not shape near-term priorities

## Archived or intentionally non-canonical docs

These docs may still exist for historical context, but they should not override the canonical docs above:
- `shared-sentiment-snapshot-implementation-plan.md`
- `shared-sentiment-snapshot-refactor.md`
- `nitter-social-implementation-checklist.md`
- `nitter-social-sentiment-design.md`

## Maintenance rule

When a feature ships:
- update the canonical doc for that topic
- remove or archive planning language elsewhere
- avoid describing shipped work as major future work in multiple places

When a feature is only exploratory:
- keep it clearly marked as deferred or conceptual
- do not let it compete with the active roadmap unless priorities actually change
