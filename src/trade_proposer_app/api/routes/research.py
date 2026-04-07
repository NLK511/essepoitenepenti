from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/performance-assessment")
async def get_performance_assessment(session: Session = Depends(get_db_session)) -> dict[str, object]:
    service = PerformanceAssessmentService(session)
    payload = service.latest_assessment()
    latest_run = payload.get("latest_run")
    latest_summary = payload.get("latest_summary") if isinstance(payload.get("latest_summary"), dict) else {}
    return {
        "job": payload.get("job"),
        "history_count": payload.get("history_count", 0),
        "latest_run": latest_run,
        "latest_assessment": latest_summary,
    }


@router.post("/performance-assessment/run")
async def run_performance_assessment(session: Session = Depends(get_db_session)):
    service = PerformanceAssessmentService(session)
    job = service.ensure_daily_job()
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        performance_assessment=service,
    ).enqueue_job(job.id or 0)
