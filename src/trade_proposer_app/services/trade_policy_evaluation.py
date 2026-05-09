from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation, PlanPolicyEvaluator
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReport, PlanReliabilityReportService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy, TradeDecisionPolicyService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


@dataclass(frozen=True)
class PolicyHealthReport:
    label: str
    reasons: list[str]
    resolved_selected_outcomes: int
    win_rate_percent: float | None
    realized_pnl: float
    calibration_gap_percent: float | None
    broker_outcome_share_percent: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "reasons": self.reasons,
            "resolved_selected_outcomes": self.resolved_selected_outcomes,
            "win_rate_percent": self.win_rate_percent,
            "realized_pnl": self.realized_pnl,
            "calibration_gap_percent": self.calibration_gap_percent,
            "broker_outcome_share_percent": self.broker_outcome_share_percent,
        }


@dataclass(frozen=True)
class TradePolicyEvaluationSummary:
    policy_evaluation: PlanPolicyEvaluation
    reliability_report: PlanReliabilityReport

    @property
    def policy_health(self) -> PolicyHealthReport:
        evaluation = self.policy_evaluation
        reasons: list[str] = []
        if evaluation.resolved_selected_outcomes < 20:
            reasons.append("thin_resolved_sample")
        if evaluation.win_rate_percent is None:
            reasons.append("no_resolved_win_rate")
        elif evaluation.win_rate_percent < 45.0:
            reasons.append("weak_selected_win_rate")
        if evaluation.realized_pnl < 0:
            reasons.append("negative_realized_pnl")
        if evaluation.calibration_gap_percent is not None and abs(evaluation.calibration_gap_percent) > 20.0:
            reasons.append("large_calibration_gap")
        broker_share = self._percentage(evaluation.broker_selected_outcomes, evaluation.selected_outcomes)
        if broker_share is not None and broker_share < 25.0:
            reasons.append("mostly_simulated_evidence")
        if evaluation.resolved_selected_outcomes >= 40 and evaluation.realized_pnl >= 0 and not reasons:
            label = "healthy"
        elif evaluation.resolved_selected_outcomes >= 20 and evaluation.realized_pnl >= 0 and "weak_selected_win_rate" not in reasons:
            label = "watch"
        elif evaluation.resolved_selected_outcomes == 0:
            label = "insufficient"
        else:
            label = "degraded"
        return PolicyHealthReport(
            label=label,
            reasons=reasons,
            resolved_selected_outcomes=evaluation.resolved_selected_outcomes,
            win_rate_percent=evaluation.win_rate_percent,
            realized_pnl=evaluation.realized_pnl,
            calibration_gap_percent=evaluation.calibration_gap_percent,
            broker_outcome_share_percent=broker_share,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_health": self.policy_health.to_dict(),
            "policy_evaluation": self.policy_evaluation.to_dict(),
            "reliability_report": self.reliability_report.to_dict(),
        }

    @staticmethod
    def _percentage(part: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round((part / total) * 100.0, 1)


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
