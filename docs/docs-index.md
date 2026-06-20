# Documentation Index

**Status:** reference

This index keeps the main documentation surface complete but lean. Detailed contracts live in `specs/`; completed plans and dated audits live in `archive/`.

## Start here

Read these first:

1. `../README.md` — repo overview and quick start
2. `getting-started.md` — setup, startup, auth, and troubleshooting
3. `operator-page-field-guide.md` — UI map and daily operator workflow
4. `glossary.md` — shared terms
5. `recommendation-methodology.md` — recommendation and plan-generation path

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
- `codebase-simplification-plan.md` — behavior-preserving code simplification backlog
- `recommendation-quality-improvement-plan.md` — active quality/calibration review backlog pending consolidation decision
- `fundamental-analysis-snapshot-implementation-plan.md` — remaining stale-coverage UI, observability, and validation follow-ups
- `industry-context-improvement-plan.md` — remaining industry-context evidence-quality and decision-role review

## Specs directory

Detailed behavior contracts live in `specs/`. They are current product truth or explicit current+target contracts, but they are not the first reading path.

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
- `specs/large-parameter-search-spec.md`
- `specs/gating-severity-alert-spec.md`

### Context, data, and analysis

- `specs/ticker-exposure-ontology-spec.md`
- `specs/market-intelligence-analysis-spec.md`
- `specs/fundamental-analysis-snapshot-spec.md`
- `specs/fundamental-valuation-integration-spec.md`
- `specs/news-provider-eligibility-spec.md`
- `specs/news-provider-reliability-spec.md`
- `specs/nitter-social-relevance-scoring.md`
- `specs/data-quality-audit-spec.md`
- `specs/bars-refresh-spec.md`
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

## Archive

Archived docs are historical context only and should not be used as current product truth.

Start with:

- `archive/README.md`
- `archive/roadmap-history.md`
- `archive/implementation-plans/` — completed implementation plans, cleanup plans, UI audits, and migration records
- `archive/audits/` — dated audit and remediation records
- `archive/redesign/` — historical redesign source docs whose stable content has been merged into current docs

## Maintenance rule

When a feature ships:

- update the canonical narrative doc and the relevant detailed spec
- archive completed implementation plans and dated audits
- keep `roadmap.md` short and current
- keep `specs/` as detailed contracts, not transient project plans
- do not leave completed work described as future work
- keep old persisted rows readable even when docs/plumbing move forward

Before adding a new doc, decide whether it is:

- narrative/current-state docs root
- detailed spec under `specs/`
- active plan/tracker
- reference
- archive

If it is a completed checklist, audit, or transient roadmap, place it under `docs/archive/` instead of the main docs root or `specs/`.
