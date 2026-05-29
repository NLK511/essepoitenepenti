# Documentation Index

**Status:** reference

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

## Doc taxonomy

Every active doc should fit exactly one category. Mixed current/target specs are allowed only when they include an explicit conformance/current-status section:
- **current behavior** — implemented product truth
- **target behavior** — intended semantics that may include a conformance gap
- **current + target behavior** — a spec with a current implementation section and an explicit target/conformance section
- **active plan** — work not yet complete
- **reference** — stable glossary/schema/raw details
- **archive** — historical context only

## Canonical current-state docs

These define implemented product truth.

### Product and behavior
- `product-thesis.md` — product goal, decision rules, and priority order
- `features-and-capabilities.md` — what the app does today and its current limits
- `roadmap.md` — active priorities only
- `user-journeys.md` — intended operator journeys

### Setup and operations
- `getting-started.md` — local setup, scripts, auth, validation, first-run checks
- `operational-scripts-reference.md` — reference for maintenance, hydration, and compare tools
- `observability-spec.md` — run correlation ids, structured observability events, health/debugger diagnostics, and cross-process log requirements
- `lean-architecture-and-docs-reconciliation-plan.md` — remaining active plan to reduce over-engineering and reconcile the docs surface
- `audit-remediation-and-autonomy-readiness-plan.md` — umbrella active plan for audit findings, safety gates, migration confidence, and autonomy readiness
- `audits/full-project-spec-code-audit-2026-05-29-post-remediation.md` — latest post-remediation full audit of spec/code/test coherence and autonomy readiness
- `audits/full-project-spec-code-audit-2026-05-29-post-remediation-plan.md` — active task plan for the latest post-remediation audit findings
- `audits/full-project-spec-code-audit-2026-05-29.md` — previous full audit of spec/code/test coherence and autonomy readiness
- `audits/full-project-spec-code-audit-2026-05-29-remediation-plan.md` — completed implementation record for the previous audit remediation
- `default-watchlists.md` — seeded watchlist pack and rationale
- `data-quality-audit-spec.md` — audit endpoint for repeated no-bars, no-news, stale-coverage, and broker-reject ticker issues

### Recommendation workflow
- `recommendation-methodology.md` — current scoring and planning pipeline
- `recommendation-plan-resolution-spec.md` — canonical plan outcome semantics
- `effective-plan-outcome-spec.md` — broker-preferred effective outcome contract used by calibration, performance, tuning, and research summaries
- `plan-reliability-report-spec.md` — canonical broker/effective reliability report for confidence, setup-family, and action cohorts
- `plan-policy-evaluator-spec.md` — canonical evaluator for scoring trade-selection policies against broker-preferred historical outcomes
- `account-risk-state-spec.md` — canonical account-risk read model for broker safety checks and kill-switch state
- `decision-sample-tuning-guide.md` — how to review and tune decision samples
- `signal-gating-benchmark-spec.md` — current decision-sample benchmark semantics used by gating review
- `signal-gating-tuning-guide.md` — current shipped signal-gating tuning workflow and calibration-related review surfaces

### Architecture and data
- `architecture.md` — runtime model and module boundaries
- `raw-details-reference.md` — stored payload and diagnostics reference
- `er-model.md` — current schema overview

## Active implementation, target behavior, and research docs

These are useful, but they are not the main current-state entry point. They must clearly label whether they describe current behavior, target behavior, or an active plan.

- `recommendation-quality-improvement-plan.md` — working tracker for recommendation-quality, calibration, and validation improvements
- `industry-context-improvement-plan.md` — active plan for making industry context evidence-rich enough to matter or shrinking its decision role if it stays neutral
- `edge-validation-standard.md` — current + target autonomy gate standard for broker-backed evidence, baselines, drawdown, concentration, and demotion/halt rules
- `signal-gating-tuning-guide.md` — current shipped signal-gating tuning workflow
- `plan-generation-tuning-spec.md` — current phase-1 behavior plus target autonomous plan-generation tuning conformance rules
- `market-intelligence-analysis-spec.md` — current + target behavior for event calendar, options, and analyst-data integration into ticker analysis
- `alpaca-paper-order-execution-spec.md` — first automated broker-execution spec for Alpaca paper trading, including audit UI and manual resubmit/cancel controls
- `broker-position-lifecycle-spec.md` — broker-backed position state and realized P&L ledger for app-submitted bracket orders
- `broker-risk-management-spec.md` — broker-backed pre-trade risk limits and manual kill switch
- `broker-position-steering-spec.md` — current + target broker steering contract for post-submit pending-order cancellation and conservative SL/TP steering
- `effective-plan-outcome-spec.md` — canonical broker-first outcome view for reconciling broker positions with simulated recommendation outcomes
- `plan-reliability-report-spec.md` — canonical broker/effective reliability report for confidence, setup-family, and action cohorts
- `plan-policy-evaluator-spec.md` — canonical evaluator for scoring trade-selection policies against broker-preferred historical outcomes
- `account-risk-state-spec.md` — canonical account-risk read model for broker safety checks and kill-switch state
- `nitter-social-relevance-scoring.md` — current Nitter relevance-ranking behavior

## Redesign history

The stable redesign material has been merged into canonical docs:
- product principles → `product-thesis.md`
- four-layer architecture → `architecture.md`
- transmission, setup families, and calibration governance → `recommendation-methodology.md`
- UI/navigation principles → `operator-page-field-guide.md`
- persistence direction → `er-model.md`

Historical source docs now live under `archive/redesign/` for provenance only.

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
- `archive/implementation-plans/p0-p4-remediation-plan-2026-05.md` — archived outcome/broker/policy/docs remediation record
- `archive/implementation-plans/p3-p4-audit-remediation-plan-2026-05.md` — archived watchlist/doc cleanup implementation record
- `archive/implementation-plans/architecture-simplification-refactor-plan-2026-05.md` — archived abstraction simplification implementation record
- `archive/redesign/` — historical redesign source docs whose stable content has been merged into canonical docs

## Maintenance rule

When a feature ships:
- update the canonical doc for that topic
- remove or archive planning language elsewhere
- avoid describing shipped work as major future work in multiple places

When a doc becomes mostly historical:
- move it to `docs/archive/`
- keep only a short pointer from active docs if needed

Before adding a new doc, check:
- Is this current behavior, target behavior, active plan, reference, or archive?
- Does this duplicate another doc?
- If shipped, is it removed from roadmap future language?
- If target-only, is it clearly marked as not fully implemented?
- Is there a test/spec/code owner for the behavior?

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
- `er-model.md`
