from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation, PlanPolicyEvaluator
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReport, PlanReliabilityReportService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy
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
    ) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def summarize(
        self,
        policy: TradeDecisionPolicy,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500_000,
    ) -> TradePolicyEvaluationSummary:
        return TradePolicyEvaluationSummary(
            policy_evaluation=PlanPolicyEvaluator(self.outcomes).evaluate(
                policy,
                evaluated_after=evaluated_after,
                evaluated_before=evaluated_before,
                limit=limit,
            ),
            reliability_report=PlanReliabilityReportService(
                self.outcomes,
                taxonomy_service=self.taxonomy_service,
            ).summarize(
                evaluated_after=evaluated_after,
                evaluated_before=evaluated_before,
                limit=limit,
            ),
        )
