import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot, Run, TickerSignalSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.builders import (
    create_industry_context_refresh_service,
    create_industry_context_service,
    create_macro_context_refresh_service,
    create_macro_context_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService

router = APIRouter(prefix="/context", tags=["context"])


def _create_job_execution_service(session: Session) -> JobExecutionService:
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        evaluations=EvaluationExecutionService(
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        macro_context_refresh=create_macro_context_refresh_service(session),
        industry_context_refresh=create_industry_context_refresh_service(session),
        macro_context=create_macro_context_service(session),
        industry_context=create_industry_context_service(session),
        recommendation_plans=RecommendationPlanRepository(session),
    )


@router.get("/macro")
async def list_macro_context_snapshots(
    limit: int = Query(default=20, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[MacroContextSnapshot]:
    return ContextSnapshotRepository(session).list_macro_context_snapshots(limit=limit, run_id=run_id)


@router.get("/macro/{snapshot_id}")
async def get_macro_context_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
) -> MacroContextSnapshot:
    snapshot = ContextSnapshotRepository(session).get_macro_context_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Macro context snapshot not found")
    return snapshot


@router.get("/industry")
async def list_industry_context_snapshots(
    industry_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[IndustryContextSnapshot]:
    return ContextSnapshotRepository(session).list_industry_context_snapshots(
        industry_key=industry_key,
        limit=limit,
        run_id=run_id,
    )


@router.get("/industry/{snapshot_id}")
async def get_industry_context_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
) -> IndustryContextSnapshot:
    snapshot = ContextSnapshotRepository(session).get_industry_context_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Industry context snapshot not found")
    return snapshot


@router.get("/ticker-signals")
async def list_ticker_signal_snapshots(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    snapshot_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[TickerSignalSnapshot]:
    normalized_ticker = ticker.strip().upper() if ticker else None
    return ContextSnapshotRepository(session).list_ticker_signal_snapshots(
        ticker=normalized_ticker,
        limit=limit,
        run_id=run_id,
        snapshot_id=snapshot_id,
    )


@router.post("/refresh/macro")
async def enqueue_macro_context_refresh(session: Session = Depends(get_db_session)) -> Run:
    service = _create_job_execution_service(session)
    job = JobRepository(session).get_or_create_system_job("manual macro context refresh", JobType.MACRO_CONTEXT_REFRESH)
    return service.enqueue_job(job.id or 0)


@router.post("/refresh/industry")
async def enqueue_industry_context_refresh(session: Session = Depends(get_db_session)) -> Run:
    service = _create_job_execution_service(session)
    job = JobRepository(session).get_or_create_system_job("manual industry context refresh", JobType.INDUSTRY_CONTEXT_REFRESH)
    return service.enqueue_job(job.id or 0)


@router.post("/refresh/macro/run-now")
async def run_macro_context_refresh_now(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _run_context_refresh_now(session, "manual macro context refresh", JobType.MACRO_CONTEXT_REFRESH)


@router.post("/refresh/industry/run-now")
async def run_industry_context_refresh_now(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _run_context_refresh_now(session, "manual industry context refresh", JobType.INDUSTRY_CONTEXT_REFRESH)


def _run_context_refresh_now(session: Session, job_name: str, job_type: JobType) -> dict[str, object]:
    jobs = JobRepository(session)
    runs = RunRepository(session)
    service = _create_job_execution_service(session)
    job = jobs.get_or_create_system_job(job_name, job_type)
    run = service.enqueue_job(job.id or 0)
    claimed = runs.claim_queued_run(run.id or 0)
    if claimed is None:
        latest_run = runs.get_run(run.id or 0)
        return {
            "run": latest_run,
            "executed": False,
            "reason": f"run {latest_run.id} is already {latest_run.status}",
        }
    completed_run, _recommendations = service.execute_claimed_run(claimed)
    payload: dict[str, object] = {
        "run": completed_run,
        "executed": True,
    }
    if completed_run.artifact_json:
        payload["artifact"] = _parse_json(completed_run.artifact_json, {})
    if completed_run.summary_json:
        payload["summary"] = _parse_json(completed_run.summary_json, {})
    return payload


def _parse_json(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
