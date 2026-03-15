from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import Run, RunOutput
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
    outputs: list[RunOutput] = repository.list_outputs_for_run(run_id)
    return {"run": run, "outputs": outputs}


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
