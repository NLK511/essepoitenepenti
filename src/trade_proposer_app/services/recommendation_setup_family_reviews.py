from __future__ import annotations

from collections import defaultdict

from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationPlanOutcome,
    RecommendationSetupFamilyReview,
    RecommendationSetupFamilyReviewSummary,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService


class RecommendationSetupFamilyReviewService:
    FAMILY_LABELS: dict[str, str] = {
        "breakout": "Breakout",
        "continuation": "Continuation",
        "mean_reversion": "Mean reversion",
        "breakdown": "Breakdown",
        "catalyst_follow_through": "Catalyst follow-through",
        "macro_beneficiary_loser": "Macro beneficiary / loser",
    }

    def __init__(self, outcomes: RecommendationOutcomeRepository) -> None:
        self.outcomes = outcomes

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        limit: int = 500,
    ) -> RecommendationSetupFamilyReviewSummary:
        normalized_setup_family = setup_family.strip().lower() if setup_family else None
        outcomes = self.outcomes.list_outcomes(
            ticker=ticker,
            run_id=run_id,
            setup_family=normalized_setup_family,
            limit=limit,
        )
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in outcomes:
            family = str(item.setup_family or "uncategorized").strip() or "uncategorized"
            grouped[family].append(item)
        family_order = [normalized_setup_family] if normalized_setup_family else list(self.FAMILY_LABELS)
        families = [self._build_family_review(family, grouped.get(family, [])) for family in family_order if family is not None]
        families.sort(key=lambda item: (item.resolved_outcomes, item.total_outcomes, item.win_outcomes), reverse=True)
        return RecommendationSetupFamilyReviewSummary(
            total_outcomes_reviewed=len(outcomes),
            families=families,
        )

    def _build_family_review(
        self,
        family: str,
        items: list[RecommendationPlanOutcome],
    ) -> RecommendationSetupFamilyReview:
        resolved = [item for item in items if item.outcome in {"win", "loss"}]
        return RecommendationSetupFamilyReview(
            family=family,
            label=self.FAMILY_LABELS.get(family, family.replace("_", " ")),
            total_outcomes=len(items),
            resolved_outcomes=len(resolved),
            open_outcomes=sum(1 for item in items if item.status == "open"),
            win_outcomes=sum(1 for item in items if item.outcome == "win"),
            loss_outcomes=sum(1 for item in items if item.outcome == "loss"),
            overall_win_rate_percent=self._win_rate(resolved),
            average_return_1d=self._average([item.horizon_return_1d for item in items]),
            average_return_3d=self._average([item.horizon_return_3d for item in items]),
            average_return_5d=self._average([item.horizon_return_5d for item in items]),
            average_mfe=self._average([item.max_favorable_excursion for item in items]),
            average_mae=self._average([item.max_adverse_excursion for item in items]),
            by_horizon=self._grouped_summary(items, group_by="horizon", default_key="unknown_horizon"),
            by_transmission_bias=self._grouped_summary(items, group_by="transmission_bias", default_key="unknown"),
            by_context_regime=self._grouped_summary(items, group_by="context_regime", default_key="mixed_context"),
        )

    def _grouped_summary(
        self,
        items: list[RecommendationPlanOutcome],
        *,
        group_by: str,
        default_key: str,
    ) -> list[RecommendationCalibrationBucket]:
        grouped: dict[str, list[RecommendationPlanOutcome]] = defaultdict(list)
        for item in items:
            key = str(getattr(item, group_by, None) or default_key).strip() or default_key
            grouped[key].append(item)
        min_required = RecommendationPlanCalibrationService.MIN_RESOLVED_COUNTS.get(group_by, 0)
        return self._build_bucket_list(grouped, min_required_resolved_count=min_required)

    def _build_bucket_list(
        self,
        grouped: dict[str, list[RecommendationPlanOutcome]],
        *,
        min_required_resolved_count: int,
    ) -> list[RecommendationCalibrationBucket]:
        results: list[RecommendationCalibrationBucket] = []
        for key, items in grouped.items():
            resolved = [item for item in items if item.outcome in {"win", "loss"}]
            resolved_count = len(resolved)
            results.append(
                RecommendationCalibrationBucket(
                    key=key,
                    label=key.replace("__", " / ").replace("_", " "),
                    total_count=len(items),
                    resolved_count=resolved_count,
                    win_count=sum(1 for item in items if item.outcome == "win"),
                    loss_count=sum(1 for item in items if item.outcome == "loss"),
                    open_count=sum(1 for item in items if item.status == "open"),
                    no_action_count=sum(1 for item in items if item.outcome == "no_action"),
                    watchlist_count=sum(1 for item in items if item.outcome == "watchlist"),
                    sample_status=RecommendationPlanCalibrationService._sample_status(
                        resolved_count,
                        min_required_resolved_count,
                    ),
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
