from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerOrderExecution
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClientError
from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService
from trade_proposer_app.services.builders import create_order_execution_service

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


@router.post("/sync")
async def sync_broker_orders(session: Session = Depends(get_db_session)) -> dict[str, object]:
    service = BrokerReconciliationService(session)
    try:
        outcome = service.sync_open_orders()
        return outcome.summary
    except AlpacaPaperClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{execution_id}")
async def get_broker_order(execution_id: int, session: Session = Depends(get_db_session)) -> BrokerOrderExecution:
    repository = BrokerOrderExecutionRepository(session)
    try:
        return repository.get(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{execution_id}/resubmit")
async def resubmit_broker_order(execution_id: int, session: Session = Depends(get_db_session)) -> BrokerOrderExecution:
    service = create_order_execution_service(session)
    try:
        return service.resubmit_execution(execution_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=404 if "not found" in message else 400, detail=message) from exc


@router.post("/{execution_id}/cancel")
async def cancel_broker_order(execution_id: int, session: Session = Depends(get_db_session)) -> BrokerOrderExecution:
    service = create_order_execution_service(session)
    try:
        return service.cancel_execution(execution_id)
    except AlpacaPaperClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=404 if "not found" in message else 400, detail=message) from exc


@router.post("/{execution_id}/refresh")
async def refresh_broker_order(execution_id: int, session: Session = Depends(get_db_session)) -> BrokerOrderExecution:
    service = create_order_execution_service(session)
    try:
        return service.refresh_execution(execution_id)
    except AlpacaPaperClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=404 if "not found" in message else 400, detail=message) from exc
