from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerOrderExecution
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository

router = APIRouter(prefix="/broker-orders", tags=["broker-orders"])


@router.get("")
async def list_broker_orders(
    run_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> list[BrokerOrderExecution]:
    repository = BrokerOrderExecutionRepository(session)
    if run_id is not None:
        return repository.list_by_run(run_id=run_id, limit=limit)
    return repository.list_all(limit=limit)


@router.get("/{execution_id}")
async def get_broker_order(execution_id: int, session: Session = Depends(get_db_session)) -> BrokerOrderExecution:
    repository = BrokerOrderExecutionRepository(session)
    try:
        return repository.get(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
