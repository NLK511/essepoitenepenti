import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import Run, SupportSnapshot
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.support_snapshots import SupportSnapshotRepository
from trade_proposer_app.services.builders import (
    create_industry_context_service,
    create_industry_support_service,
    create_macro_context_service,
    create_macro_support_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService

router = APIRouter(prefix="/support-snapshots", tags=["support-snapshots"])


def _create_job_execution_service(session: Session) -> JobExecutionService:
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        evaluations=EvaluationExecutionService(
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        macro_support=create_macro_support_service(session),
        industry_support=create_industry_support_service(session),
        macro_context=create_macro_context_service(session),
        industry_context=create_industry_context_service(session),
        recommendation_plans=RecommendationPlanRepository(session),
    )


@router.get("")
async def list_support_snapshots(
    scope: str | None = None,
    limit: int = 20,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SupportSnapshotRepository(session)
    normalized_scope = (scope or "").strip().lower() or None
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope=normalized_scope, limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": normalized_scope,
        "limit": normalized_limit,
    }


@router.get("/macro")
async def list_macro_snapshots(limit: int = 20, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SupportSnapshotRepository(session)
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope="macro", limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": "macro",
        "limit": normalized_limit,
    }


@router.get("/industry")
async def list_industry_snapshots(limit: int = 20, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SupportSnapshotRepository(session)
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope="industry", limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": "industry",
        "limit": normalized_limit,
    }


@router.post("/refresh/macro")
async def enqueue_macro_snapshot_refresh(session: Session = Depends(get_db_session)) -> Run:
    service = _create_job_execution_service(session)
    job = JobRepository(session).get_or_create_system_job("manual macro context refresh", JobType.MACRO_CONTEXT_REFRESH)
    return service.enqueue_job(job.id or 0)


@router.post("/refresh/macro/run-now")
async def run_macro_snapshot_refresh_now(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _run_snapshot_refresh_now(session, "manual macro context refresh", JobType.MACRO_CONTEXT_REFRESH)


@router.post("/refresh/industry")
async def enqueue_industry_snapshot_refresh(session: Session = Depends(get_db_session)) -> Run:
    service = _create_job_execution_service(session)
    job = JobRepository(session).get_or_create_system_job("manual industry context refresh", JobType.INDUSTRY_CONTEXT_REFRESH)
    return service.enqueue_job(job.id or 0)


@router.post("/refresh/industry/run-now")
async def run_industry_snapshot_refresh_now(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return _run_snapshot_refresh_now(session, "manual industry context refresh", JobType.INDUSTRY_CONTEXT_REFRESH)


@router.get("/{snapshot_id}")
async def get_support_snapshot(snapshot_id: int, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    repository = SupportSnapshotRepository(session)
    snapshot = repository.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Support snapshot {snapshot_id} not found")
    return _serialize_snapshot(snapshot)


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _run_snapshot_refresh_now(session: Session, job_name: str, job_type: JobType) -> dict[str, object]:
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


def _serialize_snapshot(snapshot: SupportSnapshot) -> dict[str, Any]:
    now = _normalize_datetime(datetime.now(timezone.utc))
    expires_at = _normalize_datetime(snapshot.expires_at)
    is_expired = expires_at is not None and now is not None and expires_at < now
    return {
        "id": snapshot.id,
        "scope": snapshot.scope,
        "subject_key": snapshot.subject_key,
        "subject_label": snapshot.subject_label,
        "status": snapshot.status,
        "score": snapshot.score,
        "label": snapshot.label,
        "computed_at": snapshot.computed_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "is_expired": is_expired,
        "coverage": _parse_json(snapshot.coverage_json, {}),
        "source_breakdown": _parse_json(snapshot.source_breakdown_json, {}),
        "drivers": _parse_json(snapshot.drivers_json, []),
        "signals": _parse_json(snapshot.signals_json, {}),
        "diagnostics": _parse_json(snapshot.diagnostics_json, {}),
        "summary_text": snapshot.summary_text,
        "job_id": snapshot.job_id,
        "run_id": snapshot.run_id,
    }


def _parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
