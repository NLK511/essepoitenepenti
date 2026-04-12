from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService
from trade_proposer_app.services.summary import SummaryService


DEFAULT_PROMPT_TEMPLATE = """# Performance assessment request

You are reviewing the current measured behavior of the Trade Proposer App.

Write a concise operator-facing assessment with these sections:
1. Executive summary
2. What is improving
3. Main risks or weak points
4. Recommended next actions (prioritized)
5. Confidence in this assessment

Rules:
- Be candid and evidence-led.
- Do not overclaim edge.
- Call out weak sample sizes explicitly.
- Distinguish operational issues from recommendation-quality issues.
- Prefer short bullets over long prose.

Assessment payload:
{assessment_payload_json}
"""


class PerformanceAssessmentService:
    DAILY_JOB_NAME = "Auto: Performance Assessment"
    DAILY_CRON = "0 0 * * *"
    PROMPT_PATH = Path("prompts/perf_assessment.md")

    def __init__(self, session) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.runs = RunRepository(session)
        self.settings = SettingsRepository(session)
        self.plan_repository = RecommendationPlanRepository(session)
        self.outcome_repository = RecommendationOutcomeRepository(session)

    def ensure_daily_job(self):
        jobs = self.jobs.list_all()
        for job in jobs:
            if job.name == self.DAILY_JOB_NAME:
                if job.job_type != JobType.PERFORMANCE_ASSESSMENT or job.cron != self.DAILY_CRON or not job.enabled:
                    return self.jobs.update(
                        job_id=job.id or 0,
                        name=self.DAILY_JOB_NAME,
                        job_type=JobType.PERFORMANCE_ASSESSMENT,
                        tickers=[],
                        watchlist_id=None,
                        schedule=self.DAILY_CRON,
                        enabled=True,
                    )
                return job
        return self.jobs.create(
            name=self.DAILY_JOB_NAME,
            job_type=JobType.PERFORMANCE_ASSESSMENT,
            tickers=[],
            watchlist_id=None,
            schedule=self.DAILY_CRON,
            enabled=True,
        )

    def run(self) -> dict[str, object]:
        payload = self._build_payload()
        prompt = self._build_prompt(payload)
        summary_service = SummaryService(
            summary_settings=self.settings.get_summary_settings(),
            provider_credentials=self.settings.get_provider_credential_map(),
        )
        fallback_summary = self._build_fallback_summary(payload)
        summary_result = summary_service.summarize_prompt(
            prompt,
            fallback_summary=fallback_summary,
            fallback_metadata={
                "assessment_type": "performance_assessment",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        return {
            "summary": {
                "assessment_type": "performance_assessment",
                "generated_at": generated_at,
                "content": summary_result.summary,
                "backend": summary_result.backend,
                "method": summary_result.method,
                "model": summary_result.model,
                "llm_error": summary_result.llm_error,
                "duration_seconds": summary_result.duration_seconds,
                "metrics": payload.get("headline_metrics", {}),
            },
            "artifact": {
                "assessment_type": "performance_assessment",
                "generated_at": generated_at,
                "prompt_template_path": str(self.PROMPT_PATH),
                "prompt": prompt,
                "payload": payload,
                "backend": summary_result.backend,
                "method": summary_result.method,
                "model": summary_result.model,
                "llm_error": summary_result.llm_error,
                "duration_seconds": summary_result.duration_seconds,
                "metadata": summary_result.metadata,
            },
            "warnings_found": bool(summary_result.llm_error),
        }

    def latest_assessment(self) -> dict[str, object]:
        runs = self.runs.list_runs_for_job_type(
            JobType.PERFORMANCE_ASSESSMENT,
            limit=25,
            statuses=[RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value],
        )
        latest = runs[0] if runs else None
        latest_summary = self._parse_json(latest.summary_json) if latest is not None else {}
        latest_artifact = self._parse_json(latest.artifact_json) if latest is not None else {}
        return {
            "job": self.ensure_daily_job(),
            "history_count": self.runs.count_runs_for_job_type(
                JobType.PERFORMANCE_ASSESSMENT,
                statuses=[RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value],
            ),
            "latest_run": latest,
            "latest_summary": latest_summary,
            "latest_artifact": latest_artifact,
            "windowed_assessments": self._windowed_assessments(),
        }

    def _build_payload(self) -> dict[str, object]:
        calibration = RecommendationPlanCalibrationService(self.outcome_repository).summarize(limit=500)
        baselines = RecommendationPlanBaselineService(self.plan_repository).summarize(limit=500)
        evidence = RecommendationEvidenceConcentrationService(self.outcome_repository).summarize(limit=500)
        family_review = RecommendationSetupFamilyReviewService(self.outcome_repository).summarize(limit=500)
        latest_runs = self.runs.list_latest_runs(limit=12)
        windowed_assessments = self._windowed_assessments()
        recent_run_status_counts: dict[str, int] = {}
        for run in latest_runs:
            key = str(run.status)
            recent_run_status_counts[key] = recent_run_status_counts.get(key, 0) + 1
        top_families = [
            {
                "family": item.family,
                "label": item.label,
                "resolved_outcomes": item.resolved_outcomes,
                "win_rate_percent": item.overall_win_rate_percent,
                "average_return_5d": item.average_return_5d,
            }
            for item in family_review.families[:5]
        ]
        headline_metrics = {
            "resolved_outcomes": calibration.resolved_outcomes,
            "overall_win_rate_percent": calibration.overall_win_rate_percent,
            "total_trade_plans_reviewed": baselines.total_trade_plans_reviewed,
            "actual_actionable_win_rate_percent": self._comparison_metric(baselines, "actual_actionable"),
            "actual_actionable_average_return_5d": self._baseline_metric(baselines, "actual_actionable", "average_return_5d"),
            "high_confidence_win_rate_percent": self._comparison_metric(baselines, "high_confidence_only"),
            "high_confidence_average_return_5d": self._baseline_metric(baselines, "high_confidence_only", "average_return_5d"),
            "ready_for_expansion": evidence.ready_for_expansion,
        }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "headline_metrics": headline_metrics,
            "calibration": calibration.model_dump(mode="json"),
            "baselines": baselines.model_dump(mode="json"),
            "evidence_concentration": evidence.model_dump(mode="json"),
            "windowed_assessments": windowed_assessments,
            "setup_family_review": {
                "total_outcomes_reviewed": family_review.total_outcomes_reviewed,
                "families": top_families,
            },
            "recent_operations": {
                "run_count": len(latest_runs),
                "status_counts": recent_run_status_counts,
                "latest_runs": [
                    {
                        "run_id": run.id,
                        "job_id": run.job_id,
                        "job_type": run.job_type.value,
                        "status": run.status.value if hasattr(run.status, 'value') else str(run.status),
                        "created_at": run.created_at.isoformat(),
                        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                        "error_message": run.error_message,
                    }
                    for run in latest_runs[:8]
                ],
            },
        }

    def _build_prompt(self, payload: dict[str, object]) -> str:
        template = self._load_prompt_template()
        payload_json = json.dumps(payload, indent=2, sort_keys=True, default=str)
        if "{assessment_payload_json}" in template:
            return template.replace("{assessment_payload_json}", payload_json)
        return f"{template.rstrip()}\n\nAssessment payload:\n{payload_json}\n"

    def _load_prompt_template(self) -> str:
        try:
            content = self.PROMPT_PATH.read_text(encoding="utf-8")
        except OSError:
            return DEFAULT_PROMPT_TEMPLATE
        stripped = content.strip()
        return stripped if stripped else DEFAULT_PROMPT_TEMPLATE

    @staticmethod
    def _parse_json(payload: str | None) -> dict[str, object]:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

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

    def _windowed_assessments(self) -> list[dict[str, object]]:
        now = datetime.now(timezone.utc)
        windows = [
            ("7d", now - timedelta(days=7)),
            ("30d", now - timedelta(days=30)),
            ("90d", now - timedelta(days=90)),
            ("180d", now - timedelta(days=180)),
            ("1y", now - timedelta(days=365)),
        ]
        results: list[dict[str, object]] = []
        for label, evaluated_after in windows:
            calibration = RecommendationPlanCalibrationService(self.outcome_repository).summarize(limit=500, evaluated_after=evaluated_after)
            baselines = RecommendationPlanBaselineService(self.plan_repository).summarize(limit=500, computed_after=evaluated_after)
            evidence = RecommendationEvidenceConcentrationService(self.outcome_repository).summarize(limit=500, evaluated_after=evaluated_after)
            family_review = RecommendationSetupFamilyReviewService(self.outcome_repository).summarize(limit=500, evaluated_after=evaluated_after)
            results.append(
                {
                    "window": label,
                    "evaluated_after": evaluated_after.isoformat(),
                    "resolved_outcomes": calibration.resolved_outcomes,
                    "overall_win_rate_percent": calibration.overall_win_rate_percent,
                    "calibration_brier_score": calibration.calibration_report.brier_score if calibration.calibration_report else None,
                    "calibration_ece": calibration.calibration_report.expected_calibration_error if calibration.calibration_report else None,
                    "actual_actionable_win_rate_percent": self._comparison_metric(baselines, "actual_actionable"),
                    "actual_actionable_average_return_5d": self._baseline_metric(baselines, "actual_actionable", "average_return_5d"),
                    "high_confidence_win_rate_percent": self._comparison_metric(baselines, "high_confidence_only"),
                    "high_confidence_average_return_5d": self._baseline_metric(baselines, "high_confidence_only", "average_return_5d"),
                    "family_count": len(family_review.families),
                    "ready_for_expansion": evidence.ready_for_expansion,
                }
            )
        return results

    @staticmethod
    def _build_fallback_summary(payload: dict[str, object]) -> str:
        headline = payload.get("headline_metrics", {}) if isinstance(payload.get("headline_metrics"), dict) else {}
        resolved = headline.get("resolved_outcomes", 0)
        overall_win_rate = headline.get("overall_win_rate_percent")
        actual_win_rate = headline.get("actual_actionable_win_rate_percent")
        actual_return = headline.get("actual_actionable_average_return_5d")
        high_confidence = headline.get("high_confidence_win_rate_percent")
        high_return = headline.get("high_confidence_average_return_5d")
        ready = headline.get("ready_for_expansion")
        return (
            "Executive summary\n"
            f"- Resolved outcomes reviewed: {resolved}\n"
            f"- Overall measured win rate: {overall_win_rate if overall_win_rate is not None else 'n/a'}%\n"
            f"- Actual actionable baseline win rate: {actual_win_rate if actual_win_rate is not None else 'n/a'}%\n"
            f"- Actual actionable average return 5d: {actual_return if actual_return is not None else 'n/a'}\n"
            f"- High-confidence baseline win rate: {high_confidence if high_confidence is not None else 'n/a'}%\n"
            f"- High-confidence average return 5d: {high_return if high_return is not None else 'n/a'}\n"
            f"- Evidence concentration ready for expansion: {'yes' if ready else 'no'}\n\n"
            "Recommended next actions\n"
            "- Increase resolved sample size before trusting thin cohorts.\n"
            "- Compare live actionable behavior against the simpler baseline cohorts.\n"
            "- Review recent failed or warning-heavy runs separately from recommendation-quality issues."
        )
