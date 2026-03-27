from __future__ import annotations

from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationEvidenceConcentrationCohort,
    RecommendationEvidenceConcentrationSummary,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService


class RecommendationEvidenceConcentrationService:
    def __init__(self, outcomes: RecommendationOutcomeRepository) -> None:
        self.calibration = RecommendationPlanCalibrationService(outcomes)

    def summarize(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        limit: int = 500,
    ) -> RecommendationEvidenceConcentrationSummary:
        summary = self.calibration.summarize(ticker=ticker, run_id=run_id, setup_family=setup_family, limit=limit)
        overall_win_rate = summary.overall_win_rate_percent
        overall_return = self._overall_average_return_5d(summary)
        candidate_groups = [
            ("setup_family", summary.by_setup_family),
            ("horizon", summary.by_horizon),
            ("confidence_bucket", summary.by_confidence_bucket),
            ("transmission_bias", summary.by_transmission_bias),
            ("context_regime", summary.by_context_regime),
            ("horizon_setup_family", summary.by_horizon_setup_family),
        ]
        cohorts: list[RecommendationEvidenceConcentrationCohort] = []
        for slice_name, buckets in candidate_groups:
            for bucket in buckets:
                if bucket.resolved_count <= 0:
                    continue
                cohorts.append(self._cohort(slice_name, bucket, overall_win_rate=overall_win_rate, overall_return=overall_return))
        strongest_positive = sorted(
            [cohort for cohort in cohorts if cohort.edge_vs_overall_win_rate_percent is not None and cohort.edge_vs_overall_win_rate_percent > 0],
            key=lambda item: (item.concentration_score, item.resolved_count, item.edge_vs_overall_win_rate_percent or 0.0),
            reverse=True,
        )[:6]
        weakest = sorted(
            [cohort for cohort in cohorts if cohort.edge_vs_overall_win_rate_percent is not None and cohort.edge_vs_overall_win_rate_percent < 0],
            key=lambda item: (item.concentration_score, item.edge_vs_overall_win_rate_percent or 0.0),
        )[:6]
        positive_usable = [cohort for cohort in strongest_positive if cohort.sample_status in {"usable", "strong"}]
        ready_for_expansion = len(positive_usable) >= 2 and summary.resolved_outcomes >= 30
        return RecommendationEvidenceConcentrationSummary(
            total_outcomes_reviewed=summary.total_outcomes,
            resolved_outcomes_reviewed=summary.resolved_outcomes,
            overall_win_rate_percent=overall_win_rate,
            overall_average_return_5d=overall_return,
            ready_for_expansion=ready_for_expansion,
            focus_message=self._focus_message(summary.resolved_outcomes, positive_usable, weakest),
            strongest_positive_cohorts=strongest_positive,
            weakest_cohorts=weakest,
        )

    def _cohort(
        self,
        slice_name: str,
        bucket: RecommendationCalibrationBucket,
        *,
        overall_win_rate: float | None,
        overall_return: float | None,
    ) -> RecommendationEvidenceConcentrationCohort:
        edge_win = None if bucket.win_rate_percent is None or overall_win_rate is None else round(bucket.win_rate_percent - overall_win_rate, 1)
        edge_return = None if bucket.average_return_5d is None or overall_return is None else round(bucket.average_return_5d - overall_return, 3)
        sample_multiplier = {
            "insufficient": 0.2,
            "limited": 0.45,
            "usable": 0.75,
            "strong": 1.0,
        }.get(bucket.sample_status, 0.2)
        score = max(0.0, (edge_win or 0.0) * sample_multiplier) + max(0.0, (edge_return or 0.0) * 10.0 * sample_multiplier)
        return RecommendationEvidenceConcentrationCohort(
            slice_name=slice_name,
            key=bucket.key,
            label=bucket.label,
            sample_status=bucket.sample_status,
            resolved_count=bucket.resolved_count,
            min_required_resolved_count=bucket.min_required_resolved_count,
            win_rate_percent=bucket.win_rate_percent,
            average_return_5d=bucket.average_return_5d,
            edge_vs_overall_win_rate_percent=edge_win,
            edge_vs_overall_return_5d=edge_return,
            concentration_score=round(score, 2),
            interpretation=self._interpretation(slice_name, bucket, edge_win, edge_return),
        )

    @staticmethod
    def _overall_average_return_5d(summary) -> float | None:
        weighted_sum = 0.0
        count = 0
        for bucket in summary.by_confidence_bucket:
            if bucket.average_return_5d is None or bucket.resolved_count <= 0:
                continue
            weighted_sum += bucket.average_return_5d * bucket.resolved_count
            count += bucket.resolved_count
        if count <= 0:
            return None
        return round(weighted_sum / count, 3)

    @staticmethod
    def _interpretation(
        slice_name: str,
        bucket: RecommendationCalibrationBucket,
        edge_win: float | None,
        edge_return: float | None,
    ) -> str:
        if bucket.sample_status in {"insufficient", "limited"}:
            return f"{slice_name} cohort is visible but still too thin for strong trust."
        if (edge_win or 0.0) >= 8.0 and (edge_return or 0.0) >= 0.5:
            return f"{slice_name} cohort is one of the strongest places to concentrate operator attention."
        if (edge_win or 0.0) <= -8.0:
            return f"{slice_name} cohort is currently underperforming the overall book and should stay constrained."
        return f"{slice_name} cohort is measurable, but edge concentration remains modest."

    @staticmethod
    def _focus_message(
        resolved_outcomes: int,
        positive_usable: list[RecommendationEvidenceConcentrationCohort],
        weakest: list[RecommendationEvidenceConcentrationCohort],
    ) -> str:
        if resolved_outcomes < 20:
            return "Outcome history is still thin, so the priority remains evidence collection rather than aggressive concentration."
        if not positive_usable:
            return "No cohort has yet separated cleanly enough to justify stronger concentration; keep the system conservative."
        weakest_label = weakest[0].label if weakest else "the weaker slices"
        return f"Concentrate review on the strongest usable cohorts first and keep {weakest_label} constrained until the evidence improves."
