# Documentation Index

**Status:** reference

This index keeps the main documentation surface complete but lean.

## Start here

Read these first:

1. `../README.md` — repo overview and quick start
2. `getting-started.md` — setup, startup, auth, and troubleshooting
3. `operator-page-field-guide.md` — UI map and daily operator workflow
4. `glossary.md` — shared terms
5. `recommendation-methodology.md` — recommendation and plan-generation path

## Main current-state docs

These are the primary source of truth for the product today:

- `product-thesis.md` — product goal and decision priorities
- `features-and-capabilities.md` — current implemented capabilities and limits
- `roadmap.md` — short active priorities only
- `architecture.md` — runtime model and module boundaries
- `recommendation-methodology.md` — scoring, shortlist, deep analysis, calibration, and plan framing
- `operator-page-field-guide.md` — current UI/operator flow
- `user-journeys.md` — intended operator journeys
- `er-model.md` — schema overview
- `raw-details-reference.md` — persisted payload and diagnostics reference
- `operational-scripts-reference.md` — maintenance, hydration, validation, and report scripts
- `observability-spec.md` — logs, health, observability events, and correlation ids

## Core domain specs

### Recommendation quality and outcomes

- `recommendation-plan-resolution-spec.md`
- `effective-plan-outcome-spec.md`
- `plan-reliability-report-spec.md`
- `plan-policy-evaluator-spec.md`
- `confidence-calibration-spec.md`
- `edge-validation-standard.md`
- `decision-sample-tuning-guide.md`
- `signal-gating-benchmark-spec.md`
- `signal-gating-tuning-guide.md`
- `plan-generation-tuning-spec.md`
- `large-parameter-search-spec.md`
- `gating-severity-alert-spec.md`

### Context, data, and analysis

- `ticker-exposure-ontology-spec.md`
- `market-intelligence-analysis-spec.md`
- `fundamental-analysis-snapshot-spec.md`
- `fundamental-valuation-integration-spec.md`
- `industry-context-improvement-plan.md`
- `news-provider-eligibility-spec.md`
- `news-provider-reliability-spec.md`
- `nitter-social-relevance-scoring.md`
- `data-quality-audit-spec.md`
- `bars-refresh-spec.md`
- `default-watchlists.md`

### Broker execution and safety

- `alpaca-paper-order-execution-spec.md`
- `broker-risk-management-spec.md`
- `broker-position-lifecycle-spec.md`
- `broker-position-steering-spec.md`
- `multi-broker-execution-risk-spec.md`
- `etoro-live-trading-integration-spec.md`
- `account-risk-state-spec.md`

### UI/read models and operations

- `dashboard-aggregate-performance-spec.md`
- `production-readiness-plan.md`
- `codebase-simplification-plan.md`
- `recommendation-quality-improvement-plan.md`
- `fundamental-analysis-snapshot-implementation-plan.md`

## Archive

Archived docs are historical context only and should not be used as current product truth.

Start with:

- `archive/README.md`
- `archive/roadmap-history.md`
- `archive/implementation-plans/` — completed implementation plans, cleanup plans, UI audits, and migration records
- `archive/audits/` — dated audit and remediation records
- `archive/redesign/` — historical redesign source docs whose stable content has been merged into current docs

Recently archived from the main docs surface:

- `archive/implementation-plans/multi-broker-etoro-implementation-plan.md`
- `archive/implementation-plans/audit-remediation-and-autonomy-readiness-plan.md`
- `archive/implementation-plans/lean-architecture-and-docs-reconciliation-plan.md`
- `archive/implementation-plans/ui-attention-audit-2026-05-30.md`
- `archive/implementation-plans/ui-page-content-refactor-spec-2026-05-30.md`
- `archive/audits/dead-code-audit-2026-05-29.md`
- `archive/terminology.md` — standalone terminology note merged into `glossary.md`

## Maintenance rule

When a feature ships:

- update the canonical current-state/spec doc for that topic
- archive completed implementation plans and dated audits
- keep `roadmap.md` short and current
- do not leave completed work described as future work
- keep old persisted rows readable even when docs/plumbing move forward

Before adding a new doc, decide whether it is:

- current behavior
- target behavior
- current + target behavior
- active plan
- reference
- archive

If it is a completed checklist, audit, or transient roadmap, place it under `docs/archive/` instead of the main docs root.
