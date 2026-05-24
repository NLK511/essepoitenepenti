from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.models import RecommendationWalkForwardSummary
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation


@dataclass(frozen=True)
class EdgeValidationGateReport:
    label: str
    reasons: list[str]
    resolved_selected_outcomes: int
    broker_selected_outcomes: int
    broker_outcome_share_percent: float | None
    win_rate_percent: float | None
    realized_pnl: float
    average_return_percent: float | None
    average_r_multiple: float | None
    profit_factor: float | None
    calibration_gap_percent: float | None
    walk_forward_qualified_slices: int | None
    walk_forward_promotion_recommended: bool | None
    evidence_concentration_ready_for_expansion: bool | None
    degraded_input_share_percent: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "reasons": self.reasons,
            "resolved_selected_outcomes": self.resolved_selected_outcomes,
            "broker_selected_outcomes": self.broker_selected_outcomes,
            "broker_outcome_share_percent": self.broker_outcome_share_percent,
            "win_rate_percent": self.win_rate_percent,
            "realized_pnl": self.realized_pnl,
            "average_return_percent": self.average_return_percent,
            "average_r_multiple": self.average_r_multiple,
            "profit_factor": self.profit_factor,
            "calibration_gap_percent": self.calibration_gap_percent,
            "walk_forward_qualified_slices": self.walk_forward_qualified_slices,
            "walk_forward_promotion_recommended": self.walk_forward_promotion_recommended,
            "evidence_concentration_ready_for_expansion": self.evidence_concentration_ready_for_expansion,
            "degraded_input_share_percent": self.degraded_input_share_percent,
        }


class EdgeValidationGateService:
    """Autonomy gate based on broker-preferred policy evidence."""

    MIN_SELECTED_RESOLVED = 100
    MIN_BROKER_SELECTED = 50
    MIN_BROKER_SHARE_PERCENT = 50.0
    MIN_WIN_RATE_PERCENT = 50.0
    MIN_PROFIT_FACTOR = 1.25
    MAX_ABS_CALIBRATION_GAP_PERCENT = 10.0
    MIN_WALK_FORWARD_QUALIFIED_SLICES = 3

    def evaluate(
        self,
        evaluation: PlanPolicyEvaluation,
        *,
        walk_forward_validation: RecommendationWalkForwardSummary | dict[str, Any] | None = None,
        broker_reconciliation_uncertain: bool = False,
        evidence_concentration_ready_for_expansion: bool | None = None,
        degraded_input_share_percent: float | None = None,
    ) -> EdgeValidationGateReport:
        reasons: list[str] = []
        broker_share = self._percentage(evaluation.broker_selected_outcomes, evaluation.selected_outcomes)
        if evaluation.resolved_selected_outcomes < self.MIN_SELECTED_RESOLVED:
            reasons.append("thin_selected_sample")
        if evaluation.broker_selected_outcomes < self.MIN_BROKER_SELECTED:
            reasons.append("thin_broker_sample")
        if broker_share is None or broker_share < self.MIN_BROKER_SHARE_PERCENT:
            reasons.append("simulation_heavy_evidence")
        if evaluation.win_rate_percent is None or evaluation.win_rate_percent < self.MIN_WIN_RATE_PERCENT:
            reasons.append("baseline_underperformance")
        if evaluation.realized_pnl <= 0:
            reasons.append("negative_realized_pnl")
        if evaluation.average_return_percent is not None and evaluation.average_return_percent <= 0:
            reasons.append("weak_expected_value")
        if evaluation.average_r_multiple is not None and evaluation.average_r_multiple <= 0:
            reasons.append("weak_expected_value")
        if evaluation.profit_factor is not None and evaluation.profit_factor < self.MIN_PROFIT_FACTOR:
            reasons.append("weak_profit_factor")
        if evaluation.calibration_gap_percent is not None and abs(evaluation.calibration_gap_percent) > self.MAX_ABS_CALIBRATION_GAP_PERCENT:
            reasons.append("large_calibration_gap")
        qualified_slices = self._walk_forward_value(walk_forward_validation, "qualified_slices")
        promotion_recommended = self._walk_forward_value(walk_forward_validation, "promotion_recommended")
        if isinstance(qualified_slices, int) and qualified_slices < self.MIN_WALK_FORWARD_QUALIFIED_SLICES:
            reasons.append("walk_forward_not_recommended")
        elif promotion_recommended is False:
            reasons.append("walk_forward_not_recommended")
        if evidence_concentration_ready_for_expansion is False:
            reasons.append("concentrated_edge")
        if degraded_input_share_percent is not None and degraded_input_share_percent > 50.0:
            reasons.append("degraded_input_edge")
        if broker_reconciliation_uncertain:
            reasons.append("broker_reconciliation_uncertain")

        label = self._label(reasons, evaluation)
        return EdgeValidationGateReport(
            label=label,
            reasons=reasons,
            resolved_selected_outcomes=evaluation.resolved_selected_outcomes,
            broker_selected_outcomes=evaluation.broker_selected_outcomes,
            broker_outcome_share_percent=broker_share,
            win_rate_percent=evaluation.win_rate_percent,
            realized_pnl=evaluation.realized_pnl,
            average_return_percent=evaluation.average_return_percent,
            average_r_multiple=evaluation.average_r_multiple,
            profit_factor=evaluation.profit_factor,
            calibration_gap_percent=evaluation.calibration_gap_percent,
            walk_forward_qualified_slices=qualified_slices if isinstance(qualified_slices, int) else None,
            walk_forward_promotion_recommended=promotion_recommended if isinstance(promotion_recommended, bool) else None,
            evidence_concentration_ready_for_expansion=evidence_concentration_ready_for_expansion,
            degraded_input_share_percent=degraded_input_share_percent,
        )

    @staticmethod
    def _label(reasons: list[str], evaluation: PlanPolicyEvaluation) -> str:
        if any(reason in reasons for reason in {"negative_realized_pnl", "broker_reconciliation_uncertain"}):
            return "demote_or_halt"
        if not reasons:
            return "eligible_for_cautious_expansion"
        if evaluation.resolved_selected_outcomes == 0:
            return "blocked"
        if any(reason in reasons for reason in {"thin_selected_sample", "thin_broker_sample", "simulation_heavy_evidence"}):
            return "research_only"
        return "watch"

    @staticmethod
    def _percentage(part: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round((part / total) * 100.0, 1)

    @staticmethod
    def _walk_forward_value(walk_forward: RecommendationWalkForwardSummary | dict[str, Any] | None, key: str) -> Any:
        if walk_forward is None:
            return None
        if isinstance(walk_forward, dict):
            return walk_forward.get(key)
        return getattr(walk_forward, key, None)
