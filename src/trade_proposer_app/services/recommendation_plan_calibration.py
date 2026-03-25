from __future__ import annotations

from collections import defaultdict

from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationCalibrationSummary,
    RecommendationPlanOutcome,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository


class RecommendationPlanCalibrationService:
    def __init__(self, outcomes: RecommendationOutcomeRepository) -> None:
        self.outcomes = outcomes

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        limit: int = 500,
    ) -> RecommendationCalibrationSummary:
        outcomes = self.outcomes.list_outcomes(ticker=ticker, run_id=run_id, limit=limit)
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
        )

    def _grouped_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        *,
        group_by: str,
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            raw = getattr(item, group_by, "")
            key = str(raw or "uncategorized").strip() or "uncategorized"
            grouped[key].append(item)
        results: list[RecommendationCalibrationBucket] = []
        for key, items in grouped.items():
            resolved = [item for item in items if item.outcome in {"win", "loss"}]
            results.append(
                RecommendationCalibrationBucket(
                    key=key,
                    label=key.replace("_", " "),
                    total_count=len(items),
                    resolved_count=len(resolved),
                    win_count=sum(1 for item in items if item.outcome == "win"),
                    loss_count=sum(1 for item in items if item.outcome == "loss"),
                    open_count=sum(1 for item in items if item.status == "open"),
                    no_action_count=sum(1 for item in items if item.outcome == "no_action"),
                    watchlist_count=sum(1 for item in items if item.outcome == "watchlist"),
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
