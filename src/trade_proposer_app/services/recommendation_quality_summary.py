from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationService


class RecommendationQualitySummaryService:
    WINDOW_DEFINITIONS: list[tuple[str, int]] = [
        ("7d", 7),
        ("30d", 30),
        ("90d", 90),
        ("180d", 180),
        ("1y", 365),
    ]
    METRIC_SAMPLE_LIMIT = 500_000
    DEFAULT_SUMMARY_WINDOW = "30d"

    def __init__(self, session) -> None:
        self.session = session
        self.outcomes = RecommendationOutcomeRepository(session)
        self.effective_outcomes = EffectivePlanOutcomeRepository(session)
        self.plans = RecommendationPlanRepository(session)
        self.settings = SettingsRepository(session)
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.performance = PerformanceAssessmentService(session)
        self.tuning = PlanGenerationTuningService(session)
        self.trade_policy = TradeDecisionPolicyService(session)
        self.policy_evaluation = TradePolicyEvaluationService(self.effective_outcomes)

    def summarize(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        latest_assessment = self.performance.latest_assessment()
        current_version = self.tuning._resolve_active_config_version()
        baseline_version = self.tuning.ensure_baseline_config_version()
        current_config = normalize_plan_generation_tuning_config(current_version.config)
        baseline_config = normalize_plan_generation_tuning_config(baseline_version.config)
        active_policy = self.trade_policy.active_policy()
        policy_review = self.policy_evaluation.summarize(active_policy, limit=self.METRIC_SAMPLE_LIMIT)
        walk_forward: dict[str, object] | None = None
        walk_forward_error: str | None = None
        try:
            walk_forward = PlanGenerationWalkForwardService(self.tuning).summarize(
                candidate_config=current_config,
                baseline_config=baseline_config,
                candidate_label=current_version.version_label,
                baseline_label=baseline_version.version_label,
                limit=self.METRIC_SAMPLE_LIMIT,
                lookback_days=365,
                validation_days=90,
                step_days=30,
                min_validation_resolved=int(self.settings_domains.strategy_settings().plan_generation_tuning["min_validation_resolved"]),
            ).model_dump(mode="json")
        except Exception as exc:  # pragma: no cover
            walk_forward_error = str(exc)

        windowed_summaries: list[dict[str, object]] = []
        summary: dict[str, object] | None = None
        calibration = None
        baselines = None
        evidence = None
        family_review = None
        for label, days in self.WINDOW_DEFINITIONS:
            computed_after = now - timedelta(days=days)
            evaluated_after = now - timedelta(days=days)
            calibration_window = RecommendationPlanCalibrationService(self.effective_outcomes).summarize(
                limit=self.METRIC_SAMPLE_LIMIT,
                evaluated_after=evaluated_after,
            )
            baselines_window = RecommendationPlanBaselineService(self.plans).summarize(
                limit=self.METRIC_SAMPLE_LIMIT,
                computed_after=computed_after,
            )
            evidence_window = RecommendationEvidenceConcentrationService(self.effective_outcomes).summarize(
                limit=self.METRIC_SAMPLE_LIMIT,
                evaluated_after=evaluated_after,
            )
            family_review_window = RecommendationSetupFamilyReviewService(self.effective_outcomes).summarize(
                limit=self.METRIC_SAMPLE_LIMIT,
                evaluated_after=evaluated_after,
            )
            entry_miss_window = self.outcomes.summarize_entry_miss_diagnostics(
                evaluated_after=evaluated_after,
                evaluated_before=now,
            )
            window_summary = self._summary_payload(
                calibration_window,
                baselines_window,
                evidence_window,
                family_review_window,
                entry_miss_window,
                walk_forward=None,
                walk_forward_error=None,
                window_label=label,
                computed_after=computed_after,
                computed_before=now,
                evaluated_after=evaluated_after,
                evaluated_before=now,
            )
            windowed_summaries.append(window_summary)
            if label == self.DEFAULT_SUMMARY_WINDOW:
                summary = window_summary
                calibration = calibration_window
                baselines = baselines_window
                evidence = evidence_window
                family_review = family_review_window

        if summary is None or calibration is None or baselines is None or evidence is None or family_review is None:
            raise RuntimeError("failed to build default recommendation-quality summary window")

        summary.update(
            {
                "tuning_settings": self.settings_domains.strategy_settings().to_dict(),
                "walk_forward_promotion_recommended": walk_forward.get("promotion_recommended") if isinstance(walk_forward, dict) else None,
                "walk_forward_average_win_rate_delta": walk_forward.get("average_win_rate_delta") if isinstance(walk_forward, dict) else None,
                "walk_forward_average_expected_value_delta": walk_forward.get("average_expected_value_delta") if isinstance(walk_forward, dict) else None,
                "walk_forward_error": walk_forward_error,
                "latest_assessment": latest_assessment.get("latest_summary", {}),
                "active_policy_evaluation": policy_review.policy_evaluation.to_dict(),
            }
        )
        next_actions = self._next_actions(summary)
        return {
            "summary": summary,
            "windowed_summaries": windowed_summaries,
            "calibration": calibration.model_dump(mode="json"),
            "entry_miss_diagnostics": self.outcomes.summarize_entry_miss_diagnostics(
                evaluated_after=now - timedelta(days=30),
                evaluated_before=now,
            ),
            "baselines": baselines.model_dump(mode="json"),
            "evidence_concentration": evidence.model_dump(mode="json"),
            "setup_family_review": family_review.model_dump(mode="json"),
            "reliability_report": policy_review.reliability_report.to_dict(),
            "walk_forward_validation": walk_forward,
            "next_actions": next_actions,
        }

    def _summary_payload(
        self,
        calibration,
        baselines,
        evidence,
        family_review,
        entry_miss_diagnostics: dict[str, object],
        *,
        walk_forward: dict[str, object] | None,
        walk_forward_error: str | None,
        window_label: str,
        computed_after: datetime,
        computed_before: datetime,
        evaluated_after: datetime,
        evaluated_before: datetime,
    ) -> dict[str, object]:
        quality_status = self._quality_status(calibration, evidence, walk_forward)
        return {
            "window_label": window_label,
            "computed_after": computed_after.isoformat(),
            "computed_before": computed_before.isoformat(),
            "evaluated_after": evaluated_after.isoformat(),
            "evaluated_before": evaluated_before.isoformat(),
            "status": quality_status,
            "status_reason": self._quality_status_reason(calibration, evidence, walk_forward),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "resolved_outcomes": calibration.resolved_outcomes,
            "overall_win_rate_percent": calibration.overall_win_rate_percent,
            "calibration_report": calibration.calibration_report.model_dump(mode="json") if calibration.calibration_report else None,
            "smoothed_calibration_report": calibration.smoothed_calibration_report.model_dump(mode="json") if calibration.smoothed_calibration_report else None,
            "actual_actionable_win_rate_percent": self._comparison_metric(baselines, "actual_actionable"),
            "actual_actionable_average_return_5d": self._baseline_metric(baselines, "actual_actionable", "average_return_5d"),
            "high_confidence_win_rate_percent": self._comparison_metric(baselines, "high_confidence_only"),
            "high_confidence_average_return_5d": self._baseline_metric(baselines, "high_confidence_only", "average_return_5d"),
            "ready_for_expansion": evidence.ready_for_expansion,
            "strongest_positive_count": len(evidence.strongest_positive_cohorts),
            "weakest_count": len(evidence.weakest_cohorts),
            "family_count": len(family_review.families),
            "entry_miss_diagnostics": entry_miss_diagnostics,
            "walk_forward_promotion_recommended": walk_forward.get("promotion_recommended") if isinstance(walk_forward, dict) else None,
            "walk_forward_average_win_rate_delta": walk_forward.get("average_win_rate_delta") if isinstance(walk_forward, dict) else None,
            "walk_forward_average_expected_value_delta": walk_forward.get("average_expected_value_delta") if isinstance(walk_forward, dict) else None,
            "walk_forward_error": walk_forward_error,
        }

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

    @staticmethod
    def _quality_status(calibration, evidence, walk_forward: dict[str, object] | None) -> str:
        brier = calibration.calibration_report.brier_score if calibration.calibration_report else None
        ece = calibration.calibration_report.expected_calibration_error if calibration.calibration_report else None
        walk_forward_recommended = bool(walk_forward.get("promotion_recommended")) if isinstance(walk_forward, dict) else False
        if calibration.resolved_outcomes < 20:
            return "thin"
        if evidence.ready_for_expansion and walk_forward_recommended and (brier is None or brier <= 0.25) and (ece is None or ece <= 0.15):
            return "healthy"
        if (brier is not None and brier > 0.35) or (ece is not None and ece > 0.2):
            return "needs_attention"
        return "watch"

    @staticmethod
    def _quality_status_reason(calibration, evidence, walk_forward: dict[str, object] | None) -> str:
        brier = calibration.calibration_report.brier_score if calibration.calibration_report else None
        ece = calibration.calibration_report.expected_calibration_error if calibration.calibration_report else None
        walk_forward_recommended = bool(walk_forward.get("promotion_recommended")) if isinstance(walk_forward, dict) else False
        if calibration.resolved_outcomes < 20:
            return "Too few resolved outcomes to trust calibration or walk-forward signals yet."
        if evidence.ready_for_expansion and walk_forward_recommended and (brier is None or brier <= 0.25) and (ece is None or ece <= 0.15):
            return "Confidence looks reasonable, a few groups are clearly stronger than average, and walk-forward checks agree."
        if (brier is not None and brier > 0.35) or (ece is not None and ece > 0.2):
            return "Calibration error is elevated, so confidence and promotion should stay conservative."
        if not evidence.ready_for_expansion:
            return "We still do not have a few groups that clearly outperform the rest, so trust should stay selective."
        if not walk_forward_recommended:
            return "Walk-forward validation is not yet supportive of promotion for the active tuning profile."
        return "The current signal is acceptable but not yet strong enough to mark the system healthy."

    @staticmethod
    def _next_actions(summary: dict[str, object]) -> list[str]:
        actions: list[str] = []
        if summary.get("resolved_outcomes", 0) < 20:
            actions.append("Collect more finished outcomes before trusting small pockets of performance.")
        if not summary.get("ready_for_expansion"):
            actions.append("Stay selective until a few groups clearly outperform the rest.")
        if not summary.get("walk_forward_promotion_recommended"):
            actions.append("Validate the active tuning profile against walk-forward slices before promotion.")
        if summary.get("calibration_report") and (
            (summary["calibration_report"].get("brier_score") is not None and summary["calibration_report"]["brier_score"] > 0.35) or
            (summary["calibration_report"].get("expected_calibration_error") is not None and summary["calibration_report"]["expected_calibration_error"] > 0.20)
        ):
            actions.append("Tighten calibration or reduce confidence over-correction in weak slices.")
        if not actions:
            actions.append("Maintain the current settings and watch for drift in family or horizon slices.")
        return actions
