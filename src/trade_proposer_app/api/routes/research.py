from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReportService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_walk_forward_validation import RecommendationWalkForwardValidationService
from trade_proposer_app.services.trading_performance_metrics import TradingPerformanceMetricsService

router = APIRouter(prefix="/research", tags=["research"])


def _performance_workbench_payload(session: Session, *, calibration_evaluated_after: datetime | None = None) -> dict[str, object]:
    service = PerformanceAssessmentService(session)
    payload = service.latest_assessment()
    latest_summary = payload.get("latest_summary") if isinstance(payload.get("latest_summary"), dict) else {}
    latest_artifact = payload.get("latest_artifact") if isinstance(payload.get("latest_artifact"), dict) else {}
    artifact_payload = latest_artifact.get("payload") if isinstance(latest_artifact.get("payload"), dict) else {}
    broker_performance = artifact_payload.get("broker_performance") if isinstance(artifact_payload.get("broker_performance"), dict) else None
    effective_outcomes = EffectivePlanOutcomeRepository(session)
    metrics = TradingPerformanceMetricsService(session, effective_outcomes=effective_outcomes)
    outcomes = RecommendationOutcomeRepository(session)
    calibration_summary = RecommendationPlanCalibrationService(effective_outcomes).summarize(
        evaluated_after=calibration_evaluated_after,
        limit=2000 if calibration_evaluated_after is not None else 500,
    )
    reliability_report = PlanReliabilityReportService(effective_outcomes).summarize(
        evaluated_after=calibration_evaluated_after,
        limit=5000,
    )
    walk_forward = RecommendationWalkForwardValidationService(
        effective_outcomes,
        RecommendationPlanRepository(session),
    ).summarize(
        lookback_days=365,
        validation_days=90,
        step_days=30,
        min_resolved_outcomes=20,
    )
    near_miss_winners = effective_outcomes.list_outcomes(
        entry_touched=False,
        near_entry_miss=True,
        direction_worked_without_entry=True,
        limit=200,
    )
    return {
        "job": payload.get("job"),
        "history_count": payload.get("history_count", 0),
        "latest_run": payload.get("latest_run"),
        "latest_assessment": latest_summary,
        "broker_performance": broker_performance,
        "broker_summary": metrics.summarize_broker_closed_positions().to_dict(),
        "effective_summary": metrics.summarize_effective_outcomes(limit=500).to_dict(),
        "calibration_summary": calibration_summary,
        "calibration_report": calibration_summary.calibration_report,
        "reliability_report": reliability_report.to_dict(),
        "walk_forward_validation": walk_forward,
        "near_miss_winners": near_miss_winners,
        "entry_miss_diagnostics": outcomes.summarize_entry_miss_diagnostics(),
        "windowed_assessments": payload.get("windowed_assessments", []),
    }


@router.get("/performance-assessment")
async def get_performance_assessment(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _performance_workbench_payload(session)


@router.get("/performance-workbench")
async def get_performance_workbench(
    calibration_evaluated_after: datetime | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return _performance_workbench_payload(session, calibration_evaluated_after=calibration_evaluated_after)


@router.post("/performance-assessment/run")
async def run_performance_assessment(session: Session = Depends(get_db_session)):
    service = PerformanceAssessmentService(session)
    job = service.ensure_daily_job()
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        performance_assessment=service,
    ).enqueue_job(job.id or 0)
