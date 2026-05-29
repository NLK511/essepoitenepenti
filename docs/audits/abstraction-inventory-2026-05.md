# Abstraction inventory

**Status:** reference
**Date:** 2026-05-09  
**Purpose:** name the business question for each major abstraction and decide whether it should be kept, merged, or archived.

## Decision legend

- **Keep:** unique business question; do not duplicate its logic elsewhere.
- **Keep as low-level facet:** useful calculator/repository, but not an operator-facing truth surface.
- **Compatibility only:** keep for routes/tests/scripts/debugging, but do not build new product logic on it.
- **Merge over time:** keep now, but future code should migrate toward the named canonical path.

| Contract/service | Business question | Current consumers | Decision | Reason |
|---|---|---|---|---|
| `RecommendationPlanOutcome` | What did the simulated evaluator conclude for this plan? | evaluation runs, fallback outcome analytics, audit views | Keep as low-level facet | Still needed as simulation fallback and audit evidence, but not headline truth when broker data exists. |
| `EffectivePlanOutcome` / `EffectivePlanOutcomeRepository` | What happened to this plan using broker-preferred truth? | dashboard, research, calibration, quality, tuning | Keep | Canonical outcome read path for analytics. |
| `BrokerOrderExecution` | What broker submission/audit event did the app create? | broker orders page, order execution, run detail, broker workbench | Keep | Required audit ledger for autonomous execution safety. |
| `BrokerPosition` | What app-owned broker position lifecycle is known? | broker metrics, effective outcomes, risk, broker workbench | Keep | Persisted broker outcome source of truth. |
| `TradingPerformanceMetricsService` | What are aggregate broker/effective performance metrics? | dashboard, performance assessment, research | Keep | Prevents duplicate win-rate/P&L calculations. |
| `RecommendationQualitySummaryService` | What should the quality summary API return for legacy/current consumers? | recommendation quality route/page | Merge over time | Should become a thin adapter over policy-health/reliability facets rather than another truth layer. |
| `RecommendationPlanCalibrationService` | How calibrated are confidence buckets? | quality/research/tuning | Keep as low-level facet | Distinct metric facet; not an operator-facing umbrella. |
| `RecommendationPlanBaselineService` | How do selected plan cohorts compare to simple baselines? | quality summary | Keep as low-level facet | Useful benchmark facet. |
| `RecommendationEvidenceConcentrationService` | Are wins/losses concentrated in narrow slices? | quality summary | Keep as low-level facet | Useful risk-of-overfit facet. |
| `RecommendationSetupFamilyReviewService` | Which setup families look useful/harmful? | quality summary, research | Keep as low-level facet | Useful slice review. |
| `PlanReliabilityReportService` | How reliable are active-policy cohorts? | research workbench, policy evaluation | Keep as low-level facet | Feeds canonical policy health; should not be separately reassembled in UI. |
| `TradePolicyEvaluationService` | Is the active selection policy healthy against broker-preferred outcomes? | research/quality summaries | Keep | Canonical operator-facing policy/reliability contract. |
| `PlanPolicyEvaluator` | How would one explicit policy score against historical outcomes? | active policy evaluation, future policy experiments | Keep as low-level facet | Narrow evaluator; useful for controlled comparisons. |
| `PlanReliabilityFeatureBuilder` | What normalized feature row should tuning/search consume? | plan-generation tuning | Keep | Prevents repeated feature extraction. |
| `RecommendationPlan` | What trade plan did the app propose at generation time? | UI, execution, outcomes, tuning | Keep | Immutable proposed-plan artifact; do not add new execution/reliability responsibilities. |
| `ExecutionCandidateBuilder` | Can a plan be turned into a broker-submittable order candidate? | order execution | Keep | Keeps broker candidate validation out of `RecommendationPlan`. |
| `TradeDecisionPolicyService` | What selection policy is active for live generation? | builders, orchestration, research | Keep | Canonical active policy construction. |
| `OrderExecutionService` | How are eligible plans submitted/synced with Alpaca paper? | run execution, broker routes | Keep | Execution boundary and audit row owner. |
| `BrokerRiskManager` | Is new broker exposure allowed now? | order execution, broker workbench | Keep | Trading safety guardrail. |
| `SettingsRepository` | How are legacy key/value settings persisted? | domain/mutation services, compatibility routes | Compatibility only | Persistence adapter; new product logic should use typed services. |
| `SettingsDomainService` | What are typed settings views by domain? | services/routes/builders | Keep | Canonical read facade over compatibility settings. |
| `SettingsMutationService` | How are typed settings writes applied safely? | settings routes | Keep | Canonical write facade. |
| Broker workbench route | What reconciled broker state should the operator see? | broker orders page | Keep | Centralizes cross-resource broker read model. |
| Research/performance workbench route | What reconciled research/performance state should the operator see? | research page | Keep | Centralizes expensive multi-facet read model. |
| Settings workbench route | What settings/preflight/broker context should Settings show? | settings page | Keep | Centralizes settings-page reconciliation. |
| Lower-level list/detail routes | What raw/debug records are available? | UI details, tests, scripts, API consumers | Compatibility/debug | Keep unless confirmed unused by `rg`, tests, and operator flows. |

## Rules after this inventory

1. New code should use `EffectivePlanOutcome` for analytics unless it explicitly needs simulated fallback details.
2. New operator-facing policy health should use `TradePolicyEvaluationService`.
3. New execution logic should use `ExecutionCandidateBuilder` rather than reading trade levels directly from `RecommendationPlan`.
4. New settings reads should use `SettingsDomainService` or `TradeDecisionPolicyService`, not raw setting maps.
5. New workbench routes require a real cross-resource reconciliation need.
