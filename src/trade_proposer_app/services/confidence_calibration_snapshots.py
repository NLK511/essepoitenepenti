from __future__ import annotations

import json
from datetime import datetime, timezone

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.domain.models import RecommendationCalibrationSummary
from trade_proposer_app.services.recommendation_plan_calibration import (
    RecommendationPlanCalibrationService,
)


class ConfidenceCalibrationSnapshotService:
    LIVE_CALIBRATION_LIMIT = 50_000
    ARTIFACT_KEY = "confidence_calibration_refresh"

    def __init__(self, runs, calibration_service: RecommendationPlanCalibrationService | None = None) -> None:
        self.runs = runs
        self.calibration_service = calibration_service

    def refresh(self, *, limit: int = LIVE_CALIBRATION_LIMIT) -> dict[str, object]:
        if self.calibration_service is None:
            raise RuntimeError("calibration_service is required to refresh confidence calibration snapshots")
        summary = self.calibration_service.summarize(limit=limit)
        execution_only = self.calibration_service.confidence_report(mode="execution_only", window="all", limit=limit)
        phantom_only = self.calibration_service.confidence_report(mode="phantom_only", window="all", limit=limit)
        execution_plus_phantom = self.calibration_service.confidence_report(mode="execution_plus_phantom", window="all", limit=limit)
        return {
            "schema_version": "confidence-calibration-snapshot-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "live_mode": "execution_only",
            "limit": limit,
            "live_calibration_summary": summary.model_dump(mode="json"),
            "reports": {
                "execution_only": self._dump_model(execution_only),
                "phantom_only": self._dump_model(phantom_only),
                "execution_plus_phantom": self._dump_model(execution_plus_phantom),
            },
            "warnings": self._snapshot_warnings(execution_only),
        }

    def summarize(self, *_, **__) -> RecommendationCalibrationSummary | None:
        return self.latest_summary()

    def latest_summary(self) -> RecommendationCalibrationSummary | None:
        artifact = self.latest_snapshot_artifact()
        if not artifact:
            return None
        payload = artifact.get(self.ARTIFACT_KEY)
        if not isinstance(payload, dict):
            return None
        summary_payload = payload.get("live_calibration_summary")
        if not isinstance(summary_payload, dict):
            return None
        return RecommendationCalibrationSummary.model_validate(summary_payload)

    def latest_snapshot_artifact(self) -> dict[str, object] | None:
        runs = self.runs.list_runs_for_job_type(
            JobType.RECOMMENDATION_CALIBRATION_REFRESH,
            statuses=[RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value],
            limit=10,
        )
        for run in runs:
            if not run.artifact_json:
                continue
            try:
                artifact = json.loads(run.artifact_json)
            except json.JSONDecodeError:
                continue
            if isinstance(artifact, dict) and isinstance(artifact.get(self.ARTIFACT_KEY), dict):
                return artifact
        return None

    @classmethod
    def _dump_model(cls, value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {str(key): cls._dump_model(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._dump_model(item) for item in value]
        return value

    @staticmethod
    def _snapshot_warnings(execution_only_report: dict[str, object]) -> list[str]:
        warnings = []
        summary = execution_only_report.get("summary") if isinstance(execution_only_report, dict) else None
        if isinstance(summary, dict) and summary.get("sample_status") in {"empty", "sparse", "thin"}:
            warnings.append("execution_only_calibration_sample_below_usable_threshold")
        return warnings
