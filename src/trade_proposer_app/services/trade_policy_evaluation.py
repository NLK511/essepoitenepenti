from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation, PlanPolicyEvaluator
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReport, PlanReliabilityReportService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy, TradeDecisionPolicyService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


@dataclass(frozen=True)
class TradePolicyEvaluationSummary:
    policy_evaluation: PlanPolicyEvaluation
    reliability_report: PlanReliabilityReport

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_evaluation": self.policy_evaluation.to_dict(),
            "reliability_report": self.reliability_report.to_dict(),
        }


class TradePolicyEvaluationService:
    """Canonical combined evaluation for trade policy and reliability reporting."""

    def __init__(
        self,
        outcomes: EffectivePlanOutcomeRepository,
        taxonomy_service: TickerTaxonomyService | None = None,
        policy_service: TradeDecisionPolicyService | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.policy_service = policy_service

    def summarize(
        self,
        policy: TradeDecisionPolicy,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500_000,
    ) -> TradePolicyEvaluationSummary:
        outcomes = self.outcomes.list_outcomes(
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
        policy_evaluator = PlanPolicyEvaluator(self.outcomes)
        reliability_report_service = PlanReliabilityReportService(
            self.outcomes,
            taxonomy_service=self.taxonomy_service,
        )
        return TradePolicyEvaluationSummary(
            policy_evaluation=policy_evaluator.evaluate_outcomes(policy, outcomes),
            reliability_report=reliability_report_service.summarize_outcomes(outcomes),
        )

    def summarize_active_policy(
        self,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500_000,
    ) -> TradePolicyEvaluationSummary:
        if self.policy_service is None:
            raise ValueError("policy_service is required to summarize the active policy")
        return self.summarize(
            self.policy_service.active_policy(),
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
