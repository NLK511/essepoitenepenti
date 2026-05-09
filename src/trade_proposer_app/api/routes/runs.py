from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import Run
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import ACTIVE_RUN_STATUSES, RunRepository

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs(job_type: str | None = None, limit: int = 10, session: Session = Depends(get_db_session)) -> list[Run]:
    repository = RunRepository(session)
    normalized_limit = max(1, min(int(limit), 100))
    if job_type is None or not str(job_type).strip():
        return repository.list_latest_runs(limit=normalized_limit)
    try:
        parsed_job_type = JobType.parse(job_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job_type: use a known job type value") from exc
    return repository.list_runs_for_job_type(parsed_job_type, limit=normalized_limit)


@router.get("/{run_id}")
async def get_run(run_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = RunRepository(session)
    try:
        run = repository.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context_repository = ContextSnapshotRepository(session)
    recommendation_plans = RecommendationPlanRepository(session)
    return {
        "run": run,
        "macro_context_snapshots": context_repository.list_macro_context_snapshots(run_id=run_id, limit=200),
        "industry_context_snapshots": context_repository.list_industry_context_snapshots(run_id=run_id, limit=200),
        "ticker_signal_snapshots": context_repository.list_ticker_signal_snapshots(run_id=run_id, limit=200),
        "recommendation_plans": recommendation_plans.list_plans(run_id=run_id, limit=200),
        "broker_order_executions": BrokerOrderExecutionRepository(session).list_by_run(run_id=run_id, limit=200),
    }


@router.delete("/{run_id}")
async def delete_run(run_id: int, force: bool = False, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = RunRepository(session)
    repository.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
    try:
        run = repository.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status in ACTIVE_RUN_STATUSES and not force:
        raise HTTPException(status_code=400, detail="Cannot delete runs that are queued or running; retry with force=true or recover the stale run first")
    repository.delete_run(run_id)
    return {"deleted": True, "run_id": run_id, "force": force}
