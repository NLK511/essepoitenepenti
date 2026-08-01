from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.plan_generation_walk_forward import (
    PlanGenerationWalkForwardService,
)
from trade_proposer_app.services.policy_trust_report import PolicyTrustReportService
from trade_proposer_app.services.recommendation_evidence_concentration import (
    RecommendationEvidenceConcentrationService,
)
from trade_proposer_app.services.recommendation_plan_baselines import (
    RecommendationPlanBaselineService,
)
from trade_proposer_app.services.recommendation_plan_calibration import (
    RecommendationPlanCalibrationService,
)
from trade_proposer_app.services.recommendation_setup_family_reviews import (
    RecommendationSetupFamilyReviewService,
)
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.time_windows import review_window_label, review_window_start
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationService


class RecommendationQualitySummaryService:
    # UI quality summaries are operator dashboards, not offline research sweeps.
    # Keep the default windows bounded so opening the page cannot OOM/504 on large ledgers.
    WINDOW_DEFINITIONS: list[str] = ["1d", "7d", "1m"]
    METRIC_SAMPLE_LIMIT = 1_000
    DEFAULT_SUMMARY_WINDOW = "1d"
    SUMMARY_CACHE_SETTING_KEY = "recommendation_quality_summary_cache_json"
    SUMMARY_CACHE_TTL_MINUTES = 360

    def __init__(self, session) -> None:
        self.session = session
        self.outcomes = RecommendationOutcomeRepository(session)
        self.effective_outcomes = EffectivePlanOutcomeRepository(session)
        self.plans = RecommendationPlanRepository(session)
        self.settings = SettingsRepository(session)
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.performance = PerformanceAssessmentService(session)
        self.tuning = PlanGenerationTuningService(session)
        self.policy_evaluation = TradePolicyEvaluationService(
            self.effective_outcomes, policy_service=TradeDecisionPolicyService(session)
        )

    def summarize(self, *, force_refresh: bool = False) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        if not force_refresh:
            cached = self._load_cached_summary(now)
            if cached is not None:
                return cached
        latest_assessment = self.performance.latest_assessment()
        current_version = self.tuning._resolve_active_config_version()
        baseline_version = self.tuning.ensure_baseline_config_version()
        current_config = normalize_plan_generation_tuning_config(current_version.config)
        baseline_config = normalize_plan_generation_tuning_config(baseline_version.config)
        policy_review = self.policy_evaluation.summarize_active_policy(
            limit=self.METRIC_SAMPLE_LIMIT
        )
        walk_forward, walk_forward_error = self._walk_forward_summary(
            current_config=current_config,
            baseline_config=baseline_config,
            current_label=current_version.version_label,
            baseline_label=baseline_version.version_label,
        )
        window_bundle = self._windowed_quality_summaries(now)
        summary = window_bundle["summary"]
        calibration = window_bundle["calibration"]
        baselines = window_bundle["baselines"]
        evidence = window_bundle["evidence"]
        family_review = window_bundle["family_review"]
        windowed_summaries = window_bundle["windowed_summaries"]

        policy_trust = PolicyTrustReportService(self.effective_outcomes).build(
            policy_review,
            walk_forward_validation=walk_forward,
            evidence_concentration=evidence,
            degraded_input_summary=None,
            risk_state=None,
        )
        summary.update(
            {
                "tuning_settings": self.settings_domains.strategy_settings().to_dict(),
                "walk_forward_promotion_recommended": walk_forward.get("promotion_recommended")
                if isinstance(walk_forward, dict)
                else None,
                "walk_forward_average_win_rate_delta": walk_forward.get("average_win_rate_delta")
                if isinstance(walk_forward, dict)
                else None,
                "walk_forward_average_expected_value_delta": walk_forward.get(
                    "average_expected_value_delta"
                )
                if isinstance(walk_forward, dict)
                else None,
                "walk_forward_error": walk_forward_error,
                "latest_assessment": latest_assessment.get("latest_summary", {}),
                "active_policy_evaluation": policy_review.policy_evaluation.to_dict(),
                "policy_trust": policy_trust.to_dict(),
                "edge_validation_gate": policy_trust.edge_validation_gate.to_dict(),
                "policy_health": policy_trust.policy_health_headline.to_dict(),
            }
        )
        next_actions = self._next_actions(summary)
        payload = {
            "summary": summary,
            "windowed_summaries": windowed_summaries,
            "evidence_review_checklist": self._evidence_review_checklist(summary),
            "calibration": calibration.model_dump(mode="json"),
            "entry_miss_diagnostics": self.outcomes.summarize_entry_miss_diagnostics(
                evaluated_after=now - timedelta(days=30),
                evaluated_before=now,
            ),
            "simulated_entry_miss_diagnostics": self.outcomes.summarize_entry_miss_diagnostics(
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
        self._store_cached_summary(payload)
        return payload

    def _load_cached_summary(self, now: datetime) -> dict[str, object] | None:
        raw = self.settings.get_setting_map().get(self.SUMMARY_CACHE_SETTING_KEY)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        cached_at_raw = payload.get("cached_at")
        if not isinstance(cached_at_raw, str):
            return None
        try:
            cached_at = datetime.fromisoformat(cached_at_raw)
        except ValueError:
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if now - cached_at > timedelta(minutes=self.SUMMARY_CACHE_TTL_MINUTES):
            return None
        summary_payload = payload.get("payload")
        if not isinstance(summary_payload, dict):
            return None
        summary_payload.setdefault("cache", {})
        if isinstance(summary_payload["cache"], dict):
            summary_payload["cache"].update(
                {
                    "source": "settings_cache",
                    "cached_at": cached_at.isoformat(),
                    "ttl_minutes": self.SUMMARY_CACHE_TTL_MINUTES,
                }
            )
        return summary_payload

    def _store_cached_summary(self, payload: dict[str, object]) -> None:
        wrapped = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self.settings.set_setting(self.SUMMARY_CACHE_SETTING_KEY, json.dumps(wrapped, default=str))

    def _walk_forward_summary(
        self,
        *,
        current_config: dict[str, float],
        baseline_config: dict[str, float],
        current_label: str,
        baseline_label: str,
    ) -> tuple[dict[str, object] | None, str | None]:
        try:
            return (
                PlanGenerationWalkForwardService(self.tuning)
                .summarize(
                    candidate_config=current_config,
                    baseline_config=baseline_config,
                    candidate_label=current_label,
                    baseline_label=baseline_label,
                    limit=self.METRIC_SAMPLE_LIMIT,
                    lookback_days=365,
                    validation_days=90,
                    step_days=30,
                    min_validation_resolved=int(
                        self.settings_domains.strategy_settings().plan_generation_tuning[
                            "min_validation_resolved"
                        ]
                    ),
                )
                .model_dump(mode="json"),
                None,
            )
        except Exception as exc:  # pragma: no cover
            return None, str(exc)

    def _windowed_quality_summaries(self, now: datetime) -> dict[str, object]:
        windowed_summaries: list[dict[str, object]] = []
        default_payload: dict[str, object] | None = None
        default_calibration = None
        default_baselines = None
        default_evidence = None
        default_family_review = None
        for label in self.WINDOW_DEFINITIONS:
            computed_after = review_window_start(label, now)
            evaluated_after = computed_after
            calibration = RecommendationPlanCalibrationService(self.effective_outcomes).summarize(
                mode="execution_plus_simulation",
                limit=self.METRIC_SAMPLE_LIMIT,
                evaluated_after=evaluated_after,
            )
            baselines = RecommendationPlanBaselineService(self.plans).summarize(
                limit=self.METRIC_SAMPLE_LIMIT, computed_after=computed_after
            )
            evidence = RecommendationEvidenceConcentrationService(
                self.effective_outcomes
            ).summarize(limit=self.METRIC_SAMPLE_LIMIT, evaluated_after=evaluated_after)
            family_review = RecommendationSetupFamilyReviewService(
                self.effective_outcomes
            ).summarize(limit=self.METRIC_SAMPLE_LIMIT, evaluated_after=evaluated_after)
            window_summary = self._summary_payload(
                calibration,
                baselines,
                evidence,
                family_review,
                self.outcomes.summarize_entry_miss_diagnostics(
                    evaluated_after=evaluated_after, evaluated_before=now
                ),
                walk_forward=None,
                walk_forward_error=None,
                window_label=review_window_label(label),
                computed_after=computed_after or (now - timedelta(days=3650)),
                computed_before=now,
                evaluated_after=evaluated_after or (now - timedelta(days=3650)),
                evaluated_before=now,
            )
            windowed_summaries.append(window_summary)
            if label == self.DEFAULT_SUMMARY_WINDOW:
                default_payload = window_summary
                default_calibration = calibration
                default_baselines = baselines
                default_evidence = evidence
                default_family_review = family_review
        if (
            default_payload is None
            or default_calibration is None
            or default_baselines is None
            or default_evidence is None
            or default_family_review is None
        ):
            raise RuntimeError("failed to build default recommendation-quality summary window")
        return {
            "summary": default_payload,
            "calibration": default_calibration,
            "baselines": default_baselines,
            "evidence": default_evidence,
            "family_review": default_family_review,
            "windowed_summaries": windowed_summaries,
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
            "calibration_report": calibration.calibration_report.model_dump(mode="json")
            if calibration.calibration_report
            else None,
            "smoothed_calibration_report": calibration.smoothed_calibration_report.model_dump(
                mode="json"
            )
            if calibration.smoothed_calibration_report
            else None,
            "actual_actionable_win_rate_percent": self._comparison_metric(
                baselines, "actual_actionable"
            ),
            "actual_actionable_average_return_5d": self._baseline_metric(
                baselines, "actual_actionable", "average_return_5d"
            ),
            "high_confidence_win_rate_percent": self._comparison_metric(
                baselines, "high_confidence_only"
            ),
            "high_confidence_average_return_5d": self._baseline_metric(
                baselines, "high_confidence_only", "average_return_5d"
            ),
            "ready_for_expansion": evidence.ready_for_expansion,
            "strongest_positive_count": len(evidence.strongest_positive_cohorts),
            "weakest_count": len(evidence.weakest_cohorts),
            "family_count": len(family_review.families),
            "entry_miss_diagnostics": entry_miss_diagnostics,
            "simulated_entry_miss_diagnostics": entry_miss_diagnostics,
            "walk_forward_promotion_recommended": walk_forward.get("promotion_recommended")
            if isinstance(walk_forward, dict)
            else None,
            "walk_forward_average_win_rate_delta": walk_forward.get("average_win_rate_delta")
            if isinstance(walk_forward, dict)
            else None,
            "walk_forward_average_expected_value_delta": walk_forward.get(
                "average_expected_value_delta"
            )
            if isinstance(walk_forward, dict)
            else None,
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
        brier = (
            calibration.calibration_report.brier_score if calibration.calibration_report else None
        )
        ece = (
            calibration.calibration_report.expected_calibration_error
            if calibration.calibration_report
            else None
        )
        walk_forward_recommended = (
            bool(walk_forward.get("promotion_recommended"))
            if isinstance(walk_forward, dict)
            else False
        )
        if calibration.resolved_outcomes < 20:
            return "thin"
        if (
            evidence.ready_for_expansion
            and walk_forward_recommended
            and (brier is None or brier <= 0.25)
            and (ece is None or ece <= 0.15)
        ):
            return "healthy"
        if (brier is not None and brier > 0.35) or (ece is not None and ece > 0.2):
            return "needs_attention"
        return "watch"

    @staticmethod
    def _quality_status_reason(
        calibration, evidence, walk_forward: dict[str, object] | None
    ) -> str:
        brier = (
            calibration.calibration_report.brier_score if calibration.calibration_report else None
        )
        ece = (
            calibration.calibration_report.expected_calibration_error
            if calibration.calibration_report
            else None
        )
        walk_forward_recommended = (
            bool(walk_forward.get("promotion_recommended"))
            if isinstance(walk_forward, dict)
            else False
        )
        if calibration.resolved_outcomes < 20:
            return "Too few resolved outcomes to trust calibration or walk-forward signals yet."
        if (
            evidence.ready_for_expansion
            and walk_forward_recommended
            and (brier is None or brier <= 0.25)
            and (ece is None or ece <= 0.15)
        ):
            return "Confidence looks reasonable, a few groups are clearly stronger than average, and walk-forward checks agree."
        if (brier is not None and brier > 0.35) or (ece is not None and ece > 0.2):
            return "Calibration error is elevated, so confidence and promotion should stay conservative."
        if not evidence.ready_for_expansion:
            return "We still do not have a few groups that clearly outperform the rest, so trust should stay selective."
        if not walk_forward_recommended:
            return "Walk-forward validation is not yet supportive of promotion for the active tuning profile."
        return (
            "The current signal is acceptable but not yet strong enough to mark the system healthy."
        )

    @staticmethod
    def _next_actions(summary: dict[str, object]) -> list[str]:
        actions: list[str] = []
        if summary.get("resolved_outcomes", 0) < 20:
            actions.append(
                "Collect more finished outcomes before trusting small pockets of performance."
            )
        if not summary.get("ready_for_expansion"):
            actions.append("Stay selective until a few groups clearly outperform the rest.")
        if not summary.get("walk_forward_promotion_recommended"):
            actions.append(
                "Validate the active tuning profile against walk-forward slices before promotion."
            )
        if summary.get("calibration_report") and (
            (
                summary["calibration_report"].get("brier_score") is not None
                and summary["calibration_report"]["brier_score"] > 0.35
            )
            or (
                summary["calibration_report"].get("expected_calibration_error") is not None
                and summary["calibration_report"]["expected_calibration_error"] > 0.20
            )
        ):
            actions.append(
                "Tighten calibration or reduce confidence over-correction in weak slices."
            )
        if not actions:
            actions.append(
                "Maintain the current settings and watch for drift in family or horizon slices."
            )
        return actions

    @staticmethod
    def _evidence_review_checklist(summary: dict[str, object]) -> dict[str, object]:
        resolved_outcomes = int(summary.get("resolved_outcomes") or 0)
        calibration_report = (
            summary.get("calibration_report")
            if isinstance(summary.get("calibration_report"), dict)
            else {}
        )
        brier = calibration_report.get("brier_score")
        ece = calibration_report.get("expected_calibration_error")
        calibration_usable = (
            resolved_outcomes >= 20
            and (brier is None or float(brier) <= 0.35)
            and (ece is None or float(ece) <= 0.20)
        )
        ready_for_expansion = bool(summary.get("ready_for_expansion"))
        walk_forward_promotion = bool(summary.get("walk_forward_promotion_recommended"))
        items = [
            {
                "key": "calibration_behavior",
                "status": "keep_current" if calibration_usable else "defer_thin_evidence",
                "reason": (
                    "Execution-plus-simulation calibration has enough sample and usable error."
                    if calibration_usable
                    else (
                        "Calibration remains thin or has elevated error; "
                        "keep live confidence conservative."
                    )
                ),
            },
            {
                "key": "context_ontology_macro_industry",
                "status": "keep_bounded" if ready_for_expansion else "defer_thin_evidence",
                "reason": (
                    (
                        "Cohort evidence is ready for operator review, but positive "
                        "influence still needs explicit validation."
                    )
                    if ready_for_expansion
                    else (
                        "No stable outperforming cohorts are visible enough to widen "
                        "context influence."
                    )
                ),
            },
            {
                "key": "fundamental_valuation",
                "status": "passive_context",
                "reason": (
                    "Fundamentals remain passive until point-in-time walk-forward slices "
                    "prove action-affecting value."
                ),
            },
            {
                "key": "plan_generation_tuning",
                "status": "review_candidate"
                if walk_forward_promotion and resolved_outcomes >= 20
                else "defer_thin_evidence",
                "reason": (
                    (
                        "Walk-forward promotion signal is present; candidate still needs "
                        "normal promotion review."
                    )
                    if walk_forward_promotion and resolved_outcomes >= 20
                    else "Walk-forward or sample gates do not support a tuning promotion."
                ),
            },
            {
                "key": "degraded_input_penalties",
                "status": "needs_review",
                "reason": (
                    "Review actionable degraded rows before changing penalties or hiding "
                    "degraded evidence."
                ),
            },
            {
                "key": "cheap_scan_calibration",
                "status": "defer_pending_dataset",
                "reason": (
                    "Cheap-scan calibration needs shortlisted and non-shortlisted labels "
                    "before implementation."
                ),
            },
        ]
        open_items = [item for item in items if item["status"] not in {"keep_current"}]
        return {
            "schema_version": "recommendation-quality-evidence-review-v1",
            "overall_status": "needs_review" if open_items else "complete",
            "items": items,
        }
