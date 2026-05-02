from __future__ import annotations

from collections import defaultdict

from trade_proposer_app.domain.models import RecommendationCalibrationBucket, RecommendationPlanOutcome
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


MIN_RESOLVED_COUNTS: dict[str, int] = {
    "confidence_bucket": 10,
    "setup_family": 10,
    "action": 10,
    "horizon": 12,
    "transmission_bias": 10,
    "context_regime": 10,
    "horizon_setup_family": 8,
}


class RecommendationOutcomeCohortBuilder:
    """Build shared outcome cohort buckets for calibration and family review."""

    def __init__(self, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def grouped_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        *,
        group_by: str,
        default_key: str = "uncategorized",
        min_required_resolved_count: int = 0,
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            raw = getattr(item, group_by, "")
            key = str(raw or default_key).strip() or default_key
            grouped[key].append(item)
        return self._build_bucket_list(
            grouped,
            group_by=group_by,
            min_required_resolved_count=min_required_resolved_count,
        )

    def combined_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        left_key: str,
        right_key: str,
        *,
        default_left: str,
        default_right: str,
        slice_name: str,
        min_required_resolved_count: int = 0,
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            left = str(getattr(item, left_key, None) or default_left).strip() or default_left
            right = str(getattr(item, right_key, None) or default_right).strip() or default_right
            grouped[f"{left}__{right}"].append(item)
        return self._build_bucket_list(
            grouped,
            group_by=slice_name,
            min_required_resolved_count=min_required_resolved_count,
        )

    def _build_bucket_list(
        self,
        grouped: dict[str, list[RecommendationPlanOutcome]],
        *,
        group_by: str,
        min_required_resolved_count: int,
    ) -> list[RecommendationCalibrationBucket]:
        results: list[RecommendationCalibrationBucket] = []
        for key, items in grouped.items():
            resolved = [item for item in items if item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
            resolved_count = len(resolved)
            results.append(
                RecommendationCalibrationBucket(
                    key=key,
                    label=self._bucket_label(key, group_by=group_by),
                    slice_name=group_by,
                    slice_label=self.taxonomy_service.get_analysis_slice_label(group_by),
                    total_count=len(items),
                    resolved_count=resolved_count,
                    win_count=sum(1 for item in items if item.outcome == TradeOutcome.WIN.value),
                    loss_count=sum(1 for item in items if item.outcome == TradeOutcome.LOSS.value),
                    open_count=sum(1 for item in items if item.status == OutcomeStatus.OPEN.value),
                    no_action_count=sum(1 for item in items if item.outcome == TradeOutcome.NO_ACTION.value),
                    watchlist_count=sum(1 for item in items if item.outcome == TradeOutcome.WATCHLIST.value),
                    sample_status=self._sample_status(resolved_count, min_required_resolved_count),
                    min_required_resolved_count=min_required_resolved_count,
                    win_rate_percent=self._win_rate(resolved),
                    average_return_1d=self._average([item.horizon_return_1d for item in items]),
                    average_return_3d=self._average([item.horizon_return_3d for item in items]),
                    average_return_5d=self._average([item.horizon_return_5d for item in items]),
                    average_mfe=self._average([item.max_favorable_excursion for item in items]),
                    average_mae=self._average([item.max_adverse_excursion for item in items]),
                )
            )
        results.sort(key=lambda item: (item.resolved_count, item.total_count, item.win_count), reverse=True)
        return results

    def _bucket_label(self, key: str, group_by: str = "") -> str:
        return self.taxonomy_service.get_analysis_bucket_label(group_by, key)

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
    def _win_rate(items: list[RecommendationPlanOutcome]) -> float | None:
        if not items:
            return None
        wins = sum(1 for item in items if item.outcome == TradeOutcome.WIN.value)
        return round((wins / len(items)) * 100.0, 1)

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        return round(sum(numeric) / len(numeric), 3)
