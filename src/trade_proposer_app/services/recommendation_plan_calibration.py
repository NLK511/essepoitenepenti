from __future__ import annotations

from datetime import datetime

from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationCalibrationReliabilityBin,
    RecommendationCalibrationReport,
    RecommendationCalibrationSummary,
    RecommendationPlanOutcome,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_outcome_cohorts import MIN_RESOLVED_COUNTS as OUTCOME_COHORT_MIN_RESOLVED_COUNTS, RecommendationOutcomeCohortBuilder
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationPlanCalibrationService:
    MIN_RESOLVED_COUNTS: dict[str, int] = OUTCOME_COHORT_MIN_RESOLVED_COUNTS

    def __init__(self, outcomes: RecommendationOutcomeRepository, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.cohorts = RecommendationOutcomeCohortBuilder(self.taxonomy_service)

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        resolved: str | None = None,
        outcome: str | None = None,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 500,
    ) -> RecommendationCalibrationSummary:
        outcomes = self.outcomes.list_outcomes(ticker=ticker, run_id=run_id, setup_family=setup_family, resolved=resolved, outcome=outcome, evaluated_after=evaluated_after, evaluated_before=evaluated_before, limit=limit)
        resolved = [item for item in outcomes if item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        calibration_report = self._calibration_report(outcomes)
        smoothed_calibration_report = self._smoothed_calibration_report(outcomes)
        return RecommendationCalibrationSummary(
            total_outcomes=len(outcomes),
            resolved_outcomes=len(resolved),
            open_outcomes=sum(1 for item in outcomes if item.status == OutcomeStatus.OPEN.value),
            win_outcomes=sum(1 for item in outcomes if item.outcome == TradeOutcome.WIN.value),
            loss_outcomes=sum(1 for item in outcomes if item.outcome == TradeOutcome.LOSS.value),
            no_action_outcomes=sum(1 for item in outcomes if item.outcome == TradeOutcome.NO_ACTION.value),
            watchlist_outcomes=sum(1 for item in outcomes if item.outcome == TradeOutcome.WATCHLIST.value),
            overall_win_rate_percent=self._win_rate(resolved),
            calibration_report=calibration_report,
            smoothed_calibration_report=smoothed_calibration_report,
            by_confidence_bucket=self._grouped_summary(outcomes, group_by="confidence_bucket"),
            by_setup_family=self._grouped_summary(outcomes, group_by="setup_family"),
            by_action=self._grouped_summary(outcomes, group_by="action", default_key="unknown_action"),
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
        return self.cohorts.grouped_summary(
            outcomes,
            group_by=group_by,
            default_key=default_key,
            min_required_resolved_count=self.MIN_RESOLVED_COUNTS.get(group_by, 0),
        )

    def _combined_summary(
        self,
        outcomes: list[RecommendationPlanOutcome],
        left_key: str,
        right_key: str,
        *,
        default_left: str,
        default_right: str,
    ) -> list[RecommendationCalibrationBucket]:
        return self.cohorts.combined_summary(
            outcomes,
            left_key,
            right_key,
            default_left=default_left,
            default_right=default_right,
            slice_name="horizon_setup_family",
            min_required_resolved_count=self.MIN_RESOLVED_COUNTS.get("horizon_setup_family", 0),
        )

    def _build_bucket_list(
        self,
        grouped: dict[str, list[RecommendationPlanOutcome]],
        *,
        min_required_resolved_count: int,
        group_by: str,
    ) -> list[RecommendationCalibrationBucket]:
        return self.cohorts._build_bucket_list(
            grouped,
            group_by=group_by,
            min_required_resolved_count=min_required_resolved_count,
        )

    @staticmethod
    def _sample_status(resolved_count: int, min_required_resolved_count: int) -> str:
        return RecommendationOutcomeCohortBuilder._sample_status(resolved_count, min_required_resolved_count)

    @staticmethod
    def _win_rate(items: list[RecommendationPlanOutcome]) -> float | None:
        if not items:
            return None
        wins = sum(1 for item in items if item.outcome == TradeOutcome.WIN.value)
        return round((wins / len(items)) * 100.0, 1)

    def _calibration_report(self, outcomes: list[RecommendationPlanOutcome]) -> RecommendationCalibrationReport | None:
        return self._build_calibration_report(outcomes, method="confidence_binned_reliability", version_label="confidence-reliability-v1", smoothing_strength=0.0)

    def _smoothed_calibration_report(self, outcomes: list[RecommendationPlanOutcome]) -> RecommendationCalibrationReport | None:
        return self._build_calibration_report(outcomes, method="confidence_binned_smoothed_reliability", version_label="confidence-reliability-v2-smoothed", smoothing_strength=8.0)

    def _build_calibration_report(
        self,
        outcomes: list[RecommendationPlanOutcome],
        *,
        method: str,
        version_label: str,
        smoothing_strength: float,
    ) -> RecommendationCalibrationReport | None:
        scored = [item for item in outcomes if isinstance(item.confidence_percent, (int, float)) and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        if not scored:
            return None
        bins = []
        total_brier = 0.0
        total_weighted_error = 0.0
        total_count = 0
        overall_prob = sum(1.0 if item.outcome == TradeOutcome.WIN.value else 0.0 for item in scored) / len(scored)
        for lower, upper in ((0, 20), (20, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 100)):
            bin_items = [item for item in scored if self._confidence_in_bin(float(item.confidence_percent), lower, upper)]
            if not bin_items:
                continue
            resolved_count = len(bin_items)
            raw_probs = [max(0.0, min(1.0, float(item.confidence_percent) / 100.0)) for item in bin_items]
            actuals = [1.0 if item.outcome == TradeOutcome.WIN.value else 0.0 for item in bin_items]
            avg_predicted = sum(raw_probs) / resolved_count
            avg_actual = sum(actuals) / resolved_count
            smoothed_predicted = avg_predicted if smoothing_strength <= 0 else ((avg_predicted * resolved_count) + (overall_prob * smoothing_strength)) / (resolved_count + smoothing_strength)
            bin_brier = sum((pred - actual) ** 2 for pred, actual in zip([smoothed_predicted] * resolved_count, actuals, strict=False)) / resolved_count
            calibration_error = abs(smoothed_predicted - avg_actual)
            total_brier += bin_brier * resolved_count
            total_weighted_error += calibration_error * resolved_count
            total_count += resolved_count
            bins.append(
                RecommendationCalibrationReliabilityBin(
                    bin_key=f"{lower}_{upper}",
                    bin_label=f"{lower}-{upper}",
                    sample_count=resolved_count,
                    resolved_count=resolved_count,
                    predicted_probability=round(smoothed_predicted, 4),
                    realized_win_rate_percent=round(avg_actual * 100.0, 1),
                    brier_score=round(bin_brier, 4),
                    calibration_error=round(calibration_error, 4),
                )
            )
        if total_count <= 0:
            return None
        return RecommendationCalibrationReport(
            version_label=version_label,
            method=method,
            sample_count=total_count,
            resolved_count=total_count,
            brier_score=round(total_brier / total_count, 4),
            expected_calibration_error=round(total_weighted_error / total_count, 4),
            bins=bins,
        )

    @staticmethod
    def _confidence_in_bin(confidence: float, lower: int, upper: int) -> bool:
        if upper >= 100:
            return lower <= confidence <= upper
        return lower <= confidence < upper

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        return round(sum(numeric) / len(numeric), 3)
