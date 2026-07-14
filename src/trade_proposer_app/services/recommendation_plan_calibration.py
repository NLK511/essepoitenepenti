from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import (
    RecommendationCalibrationBucket,
    RecommendationCalibrationReliabilityBin,
    RecommendationCalibrationReport,
    RecommendationCalibrationSummary,
    RecommendationPlanOutcome,
)
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.confidence_calibration_health import (
    ConfidenceCalibrationObservation,
    calibration_health_report,
)
from trade_proposer_app.services.recommendation_outcome_cohorts import (
    MIN_RESOLVED_COUNTS as OUTCOME_COHORT_MIN_RESOLVED_COUNTS,
)
from trade_proposer_app.services.recommendation_outcome_cohorts import (
    RecommendationOutcomeCohortBuilder,
)
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationPlanCalibrationService:
    MIN_RESOLVED_COUNTS: dict[str, int] = OUTCOME_COHORT_MIN_RESOLVED_COUNTS
    EXECUTION_SUCCESS_OUTCOMES = {TradeOutcome.WIN.value}
    EXECUTION_FAILURE_OUTCOMES = {TradeOutcome.LOSS.value}
    PHANTOM_SUCCESS_OUTCOMES = {"phantom_win"}
    PHANTOM_FAILURE_OUTCOMES = {"phantom_loss"}
    CALIBRATION_MODES = {"execution_only", "phantom_only", "execution_plus_phantom", "side_by_side"}
    RECENT_RESOLVED_WINDOW: int = 30
    RECENT_WINDOW_MIN_RESOLVED_FOR_CURVE: int = 20

    def __init__(self, outcomes: RecommendationOutcomeRepository, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.outcomes = outcomes
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.cohorts = RecommendationOutcomeCohortBuilder(self.taxonomy_service)

    def confidence_report(
        self,
        *,
        mode: str = "execution_only",
        window: str | None = None,
        ticker: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        outcome: str | None = None,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        computed_after: datetime | None = None,
        computed_before: datetime | None = None,
        limit: int = 500,
        now: datetime | None = None,
    ) -> dict[str, object]:
        normalized_mode = str(mode or "execution_only").strip().lower()
        if normalized_mode not in self.CALIBRATION_MODES:
            normalized_mode = "execution_only"
        if normalized_mode == "side_by_side":
            resolved_after, resolved_before = self._resolve_window(window, evaluated_after, evaluated_before, now=now)
            reports = {
                child_mode: self.confidence_report(
                    mode=child_mode,
                    window=window,
                    ticker=ticker,
                    run_id=run_id,
                    setup_family=setup_family,
                    outcome=outcome,
                    evaluated_after=resolved_after,
                    evaluated_before=resolved_before,
                    computed_after=computed_after,
                    computed_before=computed_before,
                    limit=limit,
                    now=now,
                )
                for child_mode in ("execution_only", "phantom_only", "execution_plus_phantom")
            }
            return {
                "mode": "side_by_side",
                "window": self._window_payload(window, resolved_after, resolved_before, computed_after, computed_before),
                "reports": reports,
                "warnings": self._window_warnings(computed_after=computed_after, computed_before=computed_before),
            }

        resolved_after, resolved_before = self._resolve_window(window, evaluated_after, evaluated_before, now=now)
        outcomes = self.outcomes.list_outcomes(
            ticker=ticker,
            run_id=run_id,
            setup_family=setup_family,
            resolved=None,
            outcome=outcome,
            evaluated_after=resolved_after,
            evaluated_before=resolved_before,
            limit=limit,
        )
        policy = self._label_policy(normalized_mode)
        normalized_outcomes = self._normalized_calibration_outcomes(outcomes, policy)
        calibration_report = self._build_calibration_report(
            normalized_outcomes,
            method=f"{normalized_mode}_confidence_binned_reliability",
            version_label="confidence-reliability-v1",
            smoothing_strength=0.0,
        )
        smoothed_calibration_report = self._build_calibration_report(
            normalized_outcomes,
            method=f"{normalized_mode}_confidence_binned_bayesian_reliability",
            version_label="confidence-reliability-v2-smoothed",
            smoothing_strength=8.0,
        )
        source_counts = self._outcome_counts(outcomes)
        included_count = len(normalized_outcomes)
        successes = sum(1 for item in normalized_outcomes if item.outcome == TradeOutcome.WIN.value)
        failures = sum(1 for item in normalized_outcomes if item.outcome == TradeOutcome.LOSS.value)
        warnings = self._window_warnings(computed_after=computed_after, computed_before=computed_before)
        if normalized_mode != "execution_only":
            warnings.append("phantom_outcomes_included" if normalized_mode == "execution_plus_phantom" else "phantom_only_research_view")
        if included_count < 50:
            warnings.append("calibration_sample_below_usable_threshold")
        return {
            "mode": normalized_mode,
            "window": self._window_payload(window, resolved_after, resolved_before, computed_after, computed_before, outcomes),
            "label_policy": policy,
            "source_outcome_counts": source_counts,
            "summary": {
                "total_outcomes": len(outcomes),
                "included_outcomes": included_count,
                "successes": successes,
                "failures": failures,
                "success_rate_percent": round((successes / included_count) * 100.0, 1) if included_count else None,
                "sample_status": self._confidence_sample_status(included_count),
            },
            "calibration_report": calibration_report,
            "smoothed_calibration_report": smoothed_calibration_report,
            "calibration_health": self._calibration_health(normalized_outcomes),
            "cohorts": {
                "by_confidence_bucket": self._grouped_summary(normalized_outcomes, group_by="confidence_bucket"),
                "by_setup_family": self._grouped_summary(normalized_outcomes, group_by="setup_family"),
                "by_action": self._grouped_summary(normalized_outcomes, group_by="action", default_key="unknown_action"),
                "by_horizon": self._grouped_summary(normalized_outcomes, group_by="horizon", default_key="unknown_horizon"),
                "by_transmission_bias": self._grouped_summary(normalized_outcomes, group_by="transmission_bias", default_key="unknown"),
                "by_context_regime": self._grouped_summary(normalized_outcomes, group_by="context_regime", default_key="mixed_context"),
                "by_horizon_setup_family": self._combined_summary(normalized_outcomes, "horizon", "setup_family", default_left="unknown_horizon", default_right="uncategorized"),
            },
            "warnings": warnings,
        }

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
        recent_resolved = self._recent_resolved_outcomes(resolved, limit=self.RECENT_RESOLVED_WINDOW)
        calibration_report = self._calibration_report(outcomes)
        smoothed_calibration_report = self._smoothed_calibration_report(outcomes)
        recent_calibration_report = self._calibration_report(recent_resolved)
        recent_smoothed_calibration_report = self._smoothed_calibration_report(recent_resolved)
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
            recent_calibration_report=recent_calibration_report,
            recent_smoothed_calibration_report=recent_smoothed_calibration_report,
            by_confidence_bucket=self._grouped_summary(outcomes, group_by="confidence_bucket"),
            by_setup_family=self._grouped_summary(outcomes, group_by="setup_family"),
            by_action=self._grouped_summary(outcomes, group_by="action", default_key="unknown_action"),
            by_horizon=self._grouped_summary(outcomes, group_by="horizon", default_key="unknown_horizon"),
            by_transmission_bias=self._grouped_summary(outcomes, group_by="transmission_bias", default_key="unknown"),
            by_context_regime=self._grouped_summary(outcomes, group_by="context_regime", default_key="mixed_context"),
            by_horizon_setup_family=self._combined_summary(outcomes, "horizon", "setup_family", default_left="unknown_horizon", default_right="uncategorized"),
        )

    @classmethod
    def _label_policy(cls, mode: str) -> dict[str, object]:
        if mode == "phantom_only":
            success = sorted(cls.PHANTOM_SUCCESS_OUTCOMES)
            failure = sorted(cls.PHANTOM_FAILURE_OUTCOMES)
            excluded = sorted(cls.EXECUTION_SUCCESS_OUTCOMES | cls.EXECUTION_FAILURE_OUTCOMES)
        elif mode == "execution_plus_phantom":
            success = sorted(cls.EXECUTION_SUCCESS_OUTCOMES | cls.PHANTOM_SUCCESS_OUTCOMES)
            failure = sorted(cls.EXECUTION_FAILURE_OUTCOMES | cls.PHANTOM_FAILURE_OUTCOMES)
            excluded = []
        else:
            success = sorted(cls.EXECUTION_SUCCESS_OUTCOMES)
            failure = sorted(cls.EXECUTION_FAILURE_OUTCOMES)
            excluded = sorted(cls.PHANTOM_SUCCESS_OUTCOMES | cls.PHANTOM_FAILURE_OUTCOMES)
        return {
            "included_outcomes": success + failure,
            "success_outcomes": success,
            "failure_outcomes": failure,
            "excluded_outcomes": excluded,
        }

    @staticmethod
    def _normalized_calibration_outcomes(
        outcomes: list[RecommendationPlanOutcome], policy: dict[str, object]
    ) -> list[RecommendationPlanOutcome]:
        success = {str(value) for value in policy.get("success_outcomes", []) if isinstance(value, str)}
        failure = {str(value) for value in policy.get("failure_outcomes", []) if isinstance(value, str)}
        normalized: list[RecommendationPlanOutcome] = []
        for item in outcomes:
            if item.outcome in success:
                normalized.append(item.model_copy(update={"outcome": TradeOutcome.WIN.value, "status": OutcomeStatus.RESOLVED.value}))
            elif item.outcome in failure:
                normalized.append(item.model_copy(update={"outcome": TradeOutcome.LOSS.value, "status": OutcomeStatus.RESOLVED.value}))
        return normalized

    @staticmethod
    def _outcome_counts(outcomes: list[RecommendationPlanOutcome]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in outcomes:
            counts[item.outcome] = counts.get(item.outcome, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _calibration_health(outcomes: list[RecommendationPlanOutcome]) -> dict[str, object]:
        observations = [
            ConfidenceCalibrationObservation(
                confidence_percent=float(item.confidence_percent or 0.0),
                outcome=str(item.outcome),
                evidence_date=item.evaluated_at.date().isoformat()
                if item.evaluated_at is not None
                else None,
                ticker=item.ticker,
                setup_family=item.setup_family,
                context_bias=item.transmission_bias or item.context_regime,
                expected_value=item.horizon_return_5d,
            )
            for item in outcomes
            if isinstance(item.confidence_percent, (int, float))
            and item.outcome in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}
        ]
        return calibration_health_report(observations)

    @staticmethod
    def _confidence_sample_status(sample_count: int) -> str:
        if sample_count <= 0:
            return "empty"
        if sample_count < 20:
            return "sparse"
        if sample_count < 50:
            return "thin"
        if sample_count < 200:
            return "usable"
        return "strong"

    @staticmethod
    def _resolve_window(
        window: str | None,
        evaluated_after: datetime | None,
        evaluated_before: datetime | None,
        *,
        now: datetime | None,
    ) -> tuple[datetime | None, datetime | None]:
        if evaluated_after is not None or evaluated_before is not None:
            return evaluated_after, evaluated_before
        normalized = str(window or "").strip().lower()
        if normalized in {"", "all"}:
            return None, None
        day_windows = {"7d": 7, "14d": 14, "30d": 30, "90d": 90, "180d": 180, "365d": 365}
        days = day_windows.get(normalized)
        if days is None:
            return None, None
        anchor = now or datetime.now(timezone.utc)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return anchor - timedelta(days=days), anchor

    @staticmethod
    def _window_payload(
        label: str | None,
        evaluated_after: datetime | None,
        evaluated_before: datetime | None,
        computed_after: datetime | None,
        computed_before: datetime | None,
        outcomes: list[RecommendationPlanOutcome] | None = None,
    ) -> dict[str, object]:
        evaluated_values = [item.evaluated_at for item in outcomes or [] if item.evaluated_at is not None]
        return {
            "label": label or "custom",
            "evaluated_after": evaluated_after,
            "evaluated_before": evaluated_before,
            "computed_after": computed_after,
            "computed_before": computed_before,
            "first_evaluated_at": min(evaluated_values) if evaluated_values else None,
            "last_evaluated_at": max(evaluated_values) if evaluated_values else None,
        }

    @staticmethod
    def _window_warnings(*, computed_after: datetime | None, computed_before: datetime | None) -> list[str]:
        if computed_after is None and computed_before is None:
            return []
        return ["computed_window_filter_requested_but_effective_outcomes_are_filtered_by_evaluation_time"]

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
    def _recent_resolved_outcomes(outcomes: list[RecommendationPlanOutcome], *, limit: int) -> list[RecommendationPlanOutcome]:
        if limit <= 0:
            return []
        recent: list[RecommendationPlanOutcome] = []
        for item in outcomes:
            if item.outcome not in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}:
                continue
            recent.append(item)
            if len(recent) >= limit:
                break
        return recent

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
        return self._build_calibration_report(
            outcomes,
            method="confidence_binned_bayesian_reliability",
            version_label="confidence-reliability-v2-smoothed",
            smoothing_strength=8.0,
        )

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
            predicted_probability = avg_predicted if smoothing_strength <= 0 else ((avg_predicted * resolved_count) + (overall_prob * smoothing_strength)) / (resolved_count + smoothing_strength)
            bin_brier = sum((predicted_probability - actual) ** 2 for actual in actuals) / resolved_count
            calibration_error = abs(predicted_probability - avg_actual)
            total_brier += bin_brier * resolved_count
            total_weighted_error += calibration_error * resolved_count
            total_count += resolved_count
            bins.append(
                RecommendationCalibrationReliabilityBin(
                    bin_key=f"{lower}_{upper}",
                    bin_label=f"{lower}-{upper}",
                    sample_count=resolved_count,
                    resolved_count=resolved_count,
                    predicted_probability=round(predicted_probability, 4),
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

    def _build_smoothed_calibration_report(
        self,
        outcomes: list[RecommendationPlanOutcome],
        *,
        smoothing_strength: float,
        method: str,
        version_label: str,
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
            actuals = [1.0 if item.outcome == TradeOutcome.WIN.value else 0.0 for item in bin_items]
            avg_actual = sum(actuals) / resolved_count
            smoothed_predicted = avg_actual if smoothing_strength <= 0 else ((avg_actual * resolved_count) + (overall_prob * smoothing_strength)) / (resolved_count + smoothing_strength)
            bin_brier = sum((smoothed_predicted - actual) ** 2 for actual in actuals) / resolved_count
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
