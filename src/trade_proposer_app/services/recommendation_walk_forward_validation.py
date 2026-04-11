from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import RecommendationWalkForwardSlice, RecommendationWalkForwardSummary
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService


class RecommendationWalkForwardValidationService:
    def __init__(self, outcomes: RecommendationOutcomeRepository, plans: RecommendationPlanRepository) -> None:
        self.outcomes = outcomes
        self.plans = plans

    def summarize(
        self,
        *,
        lookback_days: int = 365,
        validation_days: int = 90,
        step_days: int = 30,
        min_resolved_outcomes: int = 20,
        setup_family: str | None = None,
        limit: int = 500,
    ) -> RecommendationWalkForwardSummary:
        now = datetime.now(timezone.utc)
        lookback_days = max(30, int(lookback_days))
        validation_days = max(7, int(validation_days))
        step_days = max(1, int(step_days))
        min_resolved_outcomes = max(1, int(min_resolved_outcomes))
        start = now - timedelta(days=lookback_days)
        slice_starts: list[datetime] = []
        current = start
        while current + timedelta(days=validation_days) <= now:
            slice_starts.append(current)
            current += timedelta(days=step_days)
        slices: list[RecommendationWalkForwardSlice] = []
        for index, slice_start in enumerate(slice_starts, start=1):
            slice_end = slice_start + timedelta(days=validation_days)
            calibration = RecommendationPlanCalibrationService(self.outcomes).summarize(
                setup_family=setup_family,
                evaluated_after=slice_start,
                evaluated_before=slice_end,
                limit=limit,
            )
            baselines = RecommendationPlanBaselineService(self.plans).summarize(
                setup_family=setup_family,
                computed_after=slice_start,
                computed_before=slice_end,
                limit=limit,
            )
            evidence = RecommendationEvidenceConcentrationService(self.outcomes).summarize(
                setup_family=setup_family,
                evaluated_after=slice_start,
                evaluated_before=slice_end,
                limit=limit,
            )
            family_review = RecommendationSetupFamilyReviewService(self.outcomes).summarize(
                setup_family=setup_family,
                evaluated_after=slice_start,
                evaluated_before=slice_end,
                limit=limit,
            )
            slices.append(
                RecommendationWalkForwardSlice(
                    slice_index=index,
                    window_label=f"{slice_start.date().isoformat()} → {slice_end.date().isoformat()}",
                    computed_after=slice_start,
                    computed_before=slice_end,
                    evaluated_after=slice_start,
                    evaluated_before=slice_end,
                    total_outcomes=calibration.total_outcomes,
                    resolved_outcomes=calibration.resolved_outcomes,
                    overall_win_rate_percent=calibration.overall_win_rate_percent,
                    calibration_report=calibration.smoothed_calibration_report or calibration.calibration_report,
                    actual_actionable_win_rate_percent=self._comparison_metric(baselines, "actual_actionable"),
                    high_confidence_win_rate_percent=self._comparison_metric(baselines, "high_confidence_only"),
                    actual_actionable_average_return_5d=self._baseline_metric(baselines, "actual_actionable", "average_return_5d"),
                    high_confidence_average_return_5d=self._baseline_metric(baselines, "high_confidence_only", "average_return_5d"),
                    ready_for_expansion=evidence.ready_for_expansion,
                    setup_family_count=len(calibration.by_setup_family),
                    horizon_count=len(calibration.by_horizon),
                    transmission_bias_count=len(calibration.by_transmission_bias),
                    context_regime_count=len(calibration.by_context_regime),
                )
            )
        return RecommendationWalkForwardSummary(
            total_slices=len(slices),
            lookback_days=lookback_days,
            validation_days=validation_days,
            step_days=step_days,
            min_resolved_outcomes=min_resolved_outcomes,
            slices=slices,
        )

    @staticmethod
    def _comparison_metric(summary, key: str) -> float | None:
        for item in summary.comparisons:
            if item.key == key:
                return item.win_rate_percent
        return None

    @staticmethod
    def _baseline_metric(summary, key: str, metric: str) -> float | None:
        for item in summary.comparisons:
            if item.key == key:
                return getattr(item, metric, None)
        return None
