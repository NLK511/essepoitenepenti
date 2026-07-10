# Documentation Index

**Status:** reference

This index keeps the documentation surface complete but lean. The docs should reflect the product philosophy in `product-thesis.md`: operator trust, reproducibility, diagnosability, reliability, and measured recommendation quality before feature expansion. Detailed contracts live in `specs/`; completed plans and dated audits live in `archive/`.

## Start here

For the shortest useful path, read:

1. `../README.md` — repo overview and quick start
2. `product-thesis.md` — goals, philosophy, and decision priorities
3. `getting-started.md` — setup, startup, auth, and troubleshooting
4. `operator-page-field-guide.md` — UI map and daily operator workflow
5. `recommendation-methodology.md` — recommendation and plan-generation path

Use `glossary.md` as a reference when terms are unclear.

## Main current-state docs

These are the primary narrative source of truth for the product today:

- `product-thesis.md` — product goal and decision priorities
- `features-and-capabilities.md` — current implemented capabilities and limits
- `roadmap.md` — short active priorities only
- `architecture.md` — runtime model and module boundaries
- `recommendation-methodology.md` — scoring, shortlist, deep analysis, calibration, and plan framing
- `operator-page-field-guide.md` — current UI/operator flow
- `user-journeys.md` — intended operator journeys
- `glossary.md` — shared terms
- `er-model.md` — schema overview
- `raw-details-reference.md` — persisted payload and diagnostics reference
- `operational-scripts-reference.md` — maintenance, hydration, validation, and report scripts

## Active plans and operating trackers

- `production-readiness-plan.md` — production hardening, staging soak, external broker gates, and rollout ladder
- `docker-deployment-implementation-plan.md` — optional single-host Docker Compose deployment checklist
- `codebase-simplification-plan.md` — lightweight behavior-preserving refactor maintenance backlog
- `recommendation-quality-improvement-plan.md` — active quality and edge-validation backlog for unresolved evidence questions
- `fundamental-analysis-snapshot-implementation-plan.md` — remaining stale-coverage UI, observability, validation, and action-policy follow-ups
- `industry-context-improvement-plan.md` — industry-context evidence-quality and post-ontology role review
- `replay-validation-efficiency-remediation-plan.md` — replay validation depth, frozen-input reuse, and local-only input remediation plan

## Specs directory

Detailed behavior contracts live in `specs/`. They are current product truth or explicit current-and-target contracts, but they are not the first reading path. If a spec is fully implemented, keep it as a canonical contract and archive implementation history instead of keeping progress logs in the spec.

### Recommendation quality and outcomes

- `specs/recommendation-plan-resolution-spec.md`
- `specs/effective-plan-outcome-spec.md`
- `specs/plan-reliability-report-spec.md`
- `specs/plan-policy-evaluator-spec.md`
- `specs/confidence-calibration-spec.md`
- `specs/edge-validation-standard.md`
- `decision-sample-tuning-guide.md`
- `specs/signal-gating-benchmark-spec.md`
- `signal-gating-tuning-guide.md`
- `specs/plan-generation-tuning-spec.md`
- `specs/historical-playback-tuning-spec.md`
- `specs/tuning-workflow-ux-spec.md`
- `specs/large-parameter-search-spec.md`
- `specs/gating-severity-alert-spec.md`

### Context, data, and analysis

- `specs/ticker-exposure-ontology-spec.md`
- `specs/macro-context-shortlist-spec.md`
- `specs/context-scoring-spec.md`
- `specs/market-intelligence-analysis-spec.md`
- `specs/fundamental-analysis-snapshot-spec.md`
- `specs/fundamental-valuation-integration-spec.md`
- `specs/news-provider-eligibility-spec.md`
- `specs/news-provider-reliability-spec.md`
- `specs/nitter-social-relevance-scoring.md`
- `specs/data-quality-audit-spec.md`
- `specs/bars-refresh-spec.md`
- `specs/input-access-provenance-remediation-spec.md`
- `default-watchlists.md`

### Broker execution and safety

- `specs/alpaca-paper-order-execution-spec.md`
- `specs/broker-risk-management-spec.md`
- `specs/broker-position-lifecycle-spec.md`
- `specs/broker-position-steering-spec.md`
- `specs/multi-broker-execution-risk-spec.md`
- `specs/etoro-live-trading-integration-spec.md`
- `specs/account-risk-state-spec.md`

### UI/read models and observability

- `specs/dashboard-aggregate-performance-spec.md`
- `specs/observability-spec.md`
- `specs/production-supervision-spec.md`
- `specs/docker-deployment-spec.md`

## Archive

Archived docs are historical context only and should not be used as current product truth.

Start with:

- `archive/README.md`
- `archive/roadmap-history.md`
- `archive/implementation-plans/` — completed implementation plans, operating records, cleanup plans, UI audits, and migration records
- `archive/audits/` — dated audit and remediation records
- `archive/redesign/` — historical redesign source docs whose stable content has been merged into current docs

## Maintenance rule

When a feature ships:

- update one canonical narrative doc and one relevant spec, not several overlapping summaries
- archive completed implementation plans, checklists, and dated audits
- keep `roadmap.md` short and current
- keep `specs/` as durable contracts, not transient project plans or implementation diaries
- when a spec becomes fully implemented, remove implementation history from the spec and archive that history under `docs/archive/`
- split mixed specs into clear current-behavior and target-behavior sections
- keep `glossary.md` exhaustive; an undefined recurring term is a documentation clarity smell
- do not leave completed work described as future work
- keep old persisted rows readable even when docs/plumbing move forward

Before adding a new doc, classify it as exactly one of:

- narrative/current-state doc in `docs/`
- detailed contract in `docs/specs/`
- active plan/tracker in `docs/`
- reference in `docs/`
- historical context in `docs/archive/`

If it is a completed checklist, audit, or transient roadmap, place it under `docs/archive/` instead of the main docs root or `specs/`.
