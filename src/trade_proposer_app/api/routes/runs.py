from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import Run, RunOutput
from trade_proposer_app.repositories.runs import RunRepository

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs(session: Session = Depends(get_db_session)) -> list[Run]:
    return RunRepository(session).list_latest_runs(limit=50)


@router.get("/{run_id}")
async def get_run(run_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = RunRepository(session)
    run = repository.get_run(run_id)
    outputs: list[RunOutput] = repository.list_outputs_for_run(run_id)
    return {"run": run, "outputs": outputs}
