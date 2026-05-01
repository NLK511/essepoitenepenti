from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicy


@dataclass(frozen=True)
class PlanPolicyEvaluation:
    policy_id: str
    total_outcomes: int
    selected_outcomes: int
    resolved_selected_outcomes: int
    broker_selected_outcomes: int
    simulation_selected_outcomes: int
    win_count: int
    loss_count: int
    win_rate_percent: float | None
    average_confidence_percent: float | None
    calibration_gap_percent: float | None
    realized_pnl: float
    average_return_percent: float | None
    average_r_multiple: float | None
    profit_factor: float | None
    calibration_penalty: float | None
    robustness_label: str
    selection_rate_percent: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PlanPolicyEvaluator:
    """Score a trade-selection policy against broker-preferred effective outcomes."""

    def __init__(self, outcomes: EffectivePlanOutcomeRepository) -> None:
        self.outcomes = outcomes

    def evaluate(
        self,
        policy: TradeDecisionPolicy,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500_000,
    ) -> PlanPolicyEvaluation:
        outcomes = self.outcomes.list_outcomes(
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
        selected = [item for item in outcomes if self._selected_by_policy(item, policy)]
        resolved = self._resolved(selected)
        wins = [item for item in resolved if item.outcome == TradeOutcome.WIN.value]
        losses = [item for item in resolved if item.outcome == TradeOutcome.LOSS.value]
        win_rate = self._percentage(len(wins), len(resolved))
        average_confidence = self._average(
            [float(item.confidence_percent) for item in resolved if isinstance(item.confidence_percent, (int, float))],
            digits=2,
        )
        calibration_gap = self._calibration_gap(average_confidence, win_rate)
        realized_pnl = round(sum(float(item.realized_pnl or 0.0) for item in resolved), 4)
        return PlanPolicyEvaluation(
            policy_id=policy.policy_id,
            total_outcomes=len(outcomes),
            selected_outcomes=len(selected),
            resolved_selected_outcomes=len(resolved),
            broker_selected_outcomes=sum(1 for item in selected if item.outcome_source == "broker"),
            simulation_selected_outcomes=sum(1 for item in selected if item.outcome_source == "simulation"),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate_percent=win_rate,
            average_confidence_percent=average_confidence,
            calibration_gap_percent=calibration_gap,
            realized_pnl=realized_pnl,
            average_return_percent=self._average([float(item.realized_return_pct) for item in resolved if item.realized_return_pct is not None], digits=2),
            average_r_multiple=self._average([float(item.realized_r_multiple) for item in resolved if item.realized_r_multiple is not None], digits=4),
            profit_factor=self._profit_factor(resolved),
            calibration_penalty=abs(calibration_gap) if calibration_gap is not None else None,
            robustness_label=self._robustness_label(len(resolved), realized_pnl),
            selection_rate_percent=self._percentage(len(selected), len(outcomes)),
        )

    @staticmethod
    def _selected_by_policy(outcome: RecommendationPlanOutcome, policy: TradeDecisionPolicy) -> bool:
        if not policy.action_allowed(outcome.action):
            return False
        if not policy.setup_family_allowed(outcome.setup_family):
            return False
        if not isinstance(outcome.confidence_percent, (int, float)):
            return False
        return float(outcome.confidence_percent) >= policy.effective_confidence_threshold()

    @staticmethod
    def _resolved(outcomes: list[RecommendationPlanOutcome]) -> list[RecommendationPlanOutcome]:
        return [
            item
            for item in outcomes
            if item.status == OutcomeStatus.RESOLVED.value and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}
        ]

    @staticmethod
    def _percentage(part: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round((part / total) * 100.0, 1)

    @staticmethod
    def _average(values: list[float], *, digits: int) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), digits)

    @staticmethod
    def _calibration_gap(average_confidence: float | None, win_rate: float | None) -> float | None:
        if average_confidence is None or win_rate is None:
            return None
        return round(average_confidence - win_rate, 2)

    @staticmethod
    def _profit_factor(outcomes: list[RecommendationPlanOutcome]) -> float | None:
        if not outcomes:
            return None
        gross_profit = sum(float(item.realized_pnl or 0.0) for item in outcomes if float(item.realized_pnl or 0.0) > 0)
        gross_loss = abs(sum(float(item.realized_pnl or 0.0) for item in outcomes if float(item.realized_pnl or 0.0) < 0))
        if gross_loss <= 0:
            return None
        return round(gross_profit / gross_loss, 4)

    @staticmethod
    def _robustness_label(resolved_count: int, realized_pnl: float) -> str:
        if resolved_count >= 40 and realized_pnl >= 0:
            return "strong"
        if resolved_count >= 20:
            return "usable"
        if resolved_count >= 10:
            return "limited"
        return "insufficient"
