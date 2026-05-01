from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


@dataclass(frozen=True)
class PlanReliabilityBucket:
    slice_name: str
    key: str
    label: str
    total_count: int
    resolved_count: int
    win_count: int
    loss_count: int
    win_rate_percent: float | None
    average_confidence_percent: float | None
    calibration_gap_percent: float | None
    realized_pnl: float
    average_return_percent: float | None
    average_r_multiple: float | None
    profit_factor: float | None
    broker_outcome_count: int
    simulation_outcome_count: int
    plan_outcome_count: int
    sample_status: str
    min_required_resolved_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PlanReliabilityReport:
    total_outcomes: int
    resolved_outcomes: int
    broker_outcomes: int
    simulation_outcomes: int
    plan_outcomes: int
    by_confidence_bucket: list[PlanReliabilityBucket]
    by_setup_family: list[PlanReliabilityBucket]
    by_action: list[PlanReliabilityBucket]

    def to_dict(self) -> dict[str, object]:
        return {
            "total_outcomes": self.total_outcomes,
            "resolved_outcomes": self.resolved_outcomes,
            "broker_outcomes": self.broker_outcomes,
            "simulation_outcomes": self.simulation_outcomes,
            "plan_outcomes": self.plan_outcomes,
            "by_confidence_bucket": [bucket.to_dict() for bucket in self.by_confidence_bucket],
            "by_setup_family": [bucket.to_dict() for bucket in self.by_setup_family],
            "by_action": [bucket.to_dict() for bucket in self.by_action],
        }


class PlanReliabilityReportService:
    """Canonical broker/effective reliability cohorts for research and tuning."""

    MIN_RESOLVED_COUNTS: dict[str, int] = {
        "confidence_bucket": 10,
        "setup_family": 10,
        "action": 10,
    }

    def __init__(
        self,
        outcomes: EffectivePlanOutcomeRepository,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def summarize(
        self,
        *,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 5000,
    ) -> PlanReliabilityReport:
        outcomes = self.outcomes.list_outcomes(
            evaluated_after=evaluated_after,
            evaluated_before=evaluated_before,
            limit=limit,
        )
        resolved = self._resolved(outcomes)
        return PlanReliabilityReport(
            total_outcomes=len(outcomes),
            resolved_outcomes=len(resolved),
            broker_outcomes=sum(1 for item in outcomes if item.outcome_source == "broker"),
            simulation_outcomes=sum(1 for item in outcomes if item.outcome_source == "simulation"),
            plan_outcomes=sum(1 for item in outcomes if item.outcome_source == "plan"),
            by_confidence_bucket=self._grouped(outcomes, "confidence_bucket", default_key="unknown"),
            by_setup_family=self._grouped(outcomes, "setup_family", default_key="uncategorized"),
            by_action=self._grouped(outcomes, "action", default_key="unknown_action"),
        )

    def _grouped(
        self,
        outcomes: list[RecommendationPlanOutcome],
        slice_name: str,
        *,
        default_key: str,
    ) -> list[PlanReliabilityBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for outcome in outcomes:
            key = str(getattr(outcome, slice_name, None) or default_key).strip() or default_key
            grouped[key].append(outcome)
        buckets = [self._bucket(slice_name, key, items) for key, items in grouped.items()]
        buckets.sort(
            key=lambda item: (
                self._sample_status_rank(item.sample_status),
                item.resolved_count,
                item.win_rate_percent if item.win_rate_percent is not None else -1.0,
                item.realized_pnl,
            ),
            reverse=True,
        )
        return buckets

    def _bucket(self, slice_name: str, key: str, items: list[RecommendationPlanOutcome]) -> PlanReliabilityBucket:
        resolved = self._resolved(items)
        wins = [item for item in resolved if item.outcome == TradeOutcome.WIN.value]
        losses = [item for item in resolved if item.outcome == TradeOutcome.LOSS.value]
        win_rate = self._percentage(len(wins), len(resolved))
        average_confidence = self._average([float(item.confidence_percent) for item in resolved if isinstance(item.confidence_percent, (int, float))], digits=2)
        return PlanReliabilityBucket(
            slice_name=slice_name,
            key=key,
            label=self.taxonomy_service.get_analysis_bucket_label(slice_name, key),
            total_count=len(items),
            resolved_count=len(resolved),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate_percent=win_rate,
            average_confidence_percent=average_confidence,
            calibration_gap_percent=self._calibration_gap(average_confidence, win_rate),
            realized_pnl=round(sum(float(item.realized_pnl or 0.0) for item in resolved), 4),
            average_return_percent=self._average([float(item.realized_return_pct) for item in resolved if item.realized_return_pct is not None], digits=2),
            average_r_multiple=self._average([float(item.realized_r_multiple) for item in resolved if item.realized_r_multiple is not None], digits=4),
            profit_factor=self._profit_factor(resolved),
            broker_outcome_count=sum(1 for item in items if item.outcome_source == "broker"),
            simulation_outcome_count=sum(1 for item in items if item.outcome_source == "simulation"),
            plan_outcome_count=sum(1 for item in items if item.outcome_source == "plan"),
            sample_status=self._sample_status(len(resolved), self.MIN_RESOLVED_COUNTS.get(slice_name, 0)),
            min_required_resolved_count=self.MIN_RESOLVED_COUNTS.get(slice_name, 0),
        )

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
    def _sample_status(resolved_count: int, min_required_resolved_count: int) -> str:
        if min_required_resolved_count <= 0:
            return "usable"
        if resolved_count >= max(min_required_resolved_count * 2, min_required_resolved_count + 8):
            return "strong"
        if resolved_count >= min_required_resolved_count:
            return "usable"
        if resolved_count >= max(1, (min_required_resolved_count + 1) // 2):
            return "limited"
        return "insufficient"

    @staticmethod
    def _sample_status_rank(status: str) -> int:
        return {"strong": 3, "usable": 2, "limited": 1, "insufficient": 0}.get(status, 0)
