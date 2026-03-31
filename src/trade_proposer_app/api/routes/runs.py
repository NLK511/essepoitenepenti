from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import Run
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import ACTIVE_RUN_STATUSES, RunRepository

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs(session: Session = Depends(get_db_session)) -> list[Run]:
    return RunRepository(session).list_latest_runs(limit=50)


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
    }


@router.delete("/{run_id}")
async def delete_run(run_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = RunRepository(session)
    try:
        run = repository.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status in ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=400, detail="Cannot delete runs that are queued or running")
    repository.delete_run(run_id)
    return {"deleted": True, "run_id": run_id}
