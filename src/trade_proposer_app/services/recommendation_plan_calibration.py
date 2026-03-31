from __future__ import annotations

from collections import defaultdict

from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationCalibrationSummary,
    RecommendationPlanOutcome,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationPlanCalibrationService:
    MIN_RESOLVED_COUNTS: dict[str, int] = {
        "confidence_bucket": 10,
        "setup_family": 10,
        "horizon": 12,
        "transmission_bias": 10,
        "context_regime": 10,
        "horizon_setup_family": 8,
    }

    def __init__(self, outcomes: RecommendationOutcomeRepository, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        limit: int = 500,
    ) -> RecommendationCalibrationSummary:
        outcomes = self.outcomes.list_outcomes(ticker=ticker, run_id=run_id, setup_family=setup_family, limit=limit)
        resolved = [item for item in outcomes if item.outcome in {"win", "loss"}]
        return RecommendationCalibrationSummary(
            total_outcomes=len(outcomes),
            resolved_outcomes=len(resolved),
            open_outcomes=sum(1 for item in outcomes if item.status == "open"),
            win_outcomes=sum(1 for item in outcomes if item.outcome == "win"),
            loss_outcomes=sum(1 for item in outcomes if item.outcome == "loss"),
            no_action_outcomes=sum(1 for item in outcomes if item.outcome == "no_action"),
            watchlist_outcomes=sum(1 for item in outcomes if item.outcome == "watchlist"),
            overall_win_rate_percent=self._win_rate(resolved),
            by_confidence_bucket=self._grouped_summary(outcomes, group_by="confidence_bucket"),
            by_setup_family=self._grouped_summary(outcomes, group_by="setup_family"),
            by_horizon=self._grouped_summary(outcomes, group_by="horizon", default_key="unknown_horizon"),
            by_transmission_bias=self._grouped_summary(outcomes, group_by="transmission_bias", default_key="unknown"),
            by_context_regime=self._grouped_summary(outcomes, group_by="context_regime", default_key="mixed_context"),
            by_horizon_setup_family=self._combined_summary(outcomes, "horizon", "setup_family", default_left="unknown_horizon", default_right="uncategorized"),
        )

    def _grouped_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        *,
        group_by: str,
        default_key: str = "uncategorized",
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            raw = getattr(item, group_by, "")
            key = str(raw or default_key).strip() or default_key
            grouped[key].append(item)
        return self._build_bucket_list(grouped, min_required_resolved_count=self.MIN_RESOLVED_COUNTS.get(group_by, 0), group_by=group_by)

    def _combined_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        left_key: str,
        right_key: str,
        *,
        default_left: str,
        default_right: str,
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            left = str(getattr(item, left_key, None) or default_left).strip() or default_left
            right = str(getattr(item, right_key, None) or default_right).strip() or default_right
            grouped[f"{left}__{right}"].append(item)
        return self._build_bucket_list(grouped, min_required_resolved_count=self.MIN_RESOLVED_COUNTS.get("horizon_setup_family", 0), group_by="horizon_setup_family")

    def _build_bucket_list(
        self,
        grouped: dict[str, list[RecommendationPlanOutcome]],
        *,
        min_required_resolved_count: int,
        group_by: str,
    ) -> list[RecommendationCalibrationBucket]:
        results: list[RecommendationCalibrationBucket] = []
        for key, items in grouped.items():
            resolved = [item for item in items if item.outcome in {"win", "loss"}]
            resolved_count = len(resolved)
            results.append(
                RecommendationCalibrationBucket(
                    key=key,
                    label=self._bucket_label(key, group_by=group_by),
                    slice_name=group_by,
                    slice_label=self.taxonomy_service.get_analysis_slice_label(group_by),
                    total_count=len(items),
                    resolved_count=resolved_count,
                    win_count=sum(1 for item in items if item.outcome == "win"),
                    loss_count=sum(1 for item in items if item.outcome == "loss"),
                    open_count=sum(1 for item in items if item.status == "open"),
                    no_action_count=sum(1 for item in items if item.outcome == "no_action"),
                    watchlist_count=sum(1 for item in items if item.outcome == "watchlist"),
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
        wins = sum(1 for item in items if item.outcome == "win")
        return round((wins / len(items)) * 100.0, 1)

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        return round(sum(numeric) / len(numeric), 3)
