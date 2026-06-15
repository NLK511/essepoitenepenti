from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerOrderExecution
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClientError
from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService
from trade_proposer_app.services.builders import create_order_execution_service

router = APIRouter(prefix="/broker-orders", tags=["broker-orders"])


class BrokerManualActionRequest(BaseModel):
    confirmation_text: str = ""


@router.get("")
async def list_broker_orders(
    run_id: int | None = Query(default=None),
    broker_account_id: str | None = Query(default=None),
    broker: str | None = Query(default=None),
    account_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> list[BrokerOrderExecution]:
    repository = BrokerOrderExecutionRepository(session)
    if any([run_id is not None, broker_account_id, broker, account_mode, status]):
        return repository.list_filtered(
            run_id=run_id,
            broker_account_id=broker_account_id,
            broker=broker,
            account_mode=account_mode,
            status=status,
            limit=limit,
        )
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
async def get_broker_order(
    execution_id: int, session: Session = Depends(get_db_session)
) -> BrokerOrderExecution:
    repository = BrokerOrderExecutionRepository(session)
    try:
        return repository.get(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{execution_id}/resubmit")
async def resubmit_broker_order(
    execution_id: int,
    request: BrokerManualActionRequest | None = None,
    session: Session = Depends(get_db_session),
) -> BrokerOrderExecution:
    _require_etoro_live_manual_confirmation(
        session, execution_id, operation="resubmit", request=request
    )
    service = create_order_execution_service(session)
    try:
        return service.resubmit_execution(execution_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if "not found" in message else 400, detail=message
        ) from exc


@router.post("/{execution_id}/cancel")
async def cancel_broker_order(
    execution_id: int,
    request: BrokerManualActionRequest | None = None,
    session: Session = Depends(get_db_session),
) -> BrokerOrderExecution:
    _require_etoro_live_manual_confirmation(
        session, execution_id, operation="cancel", request=request
    )
    service = create_order_execution_service(session)
    try:
        return service.cancel_execution(execution_id)
    except AlpacaPaperClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if "not found" in message else 400, detail=message
        ) from exc


@router.post("/{execution_id}/refresh")
async def refresh_broker_order(
    execution_id: int, session: Session = Depends(get_db_session)
) -> BrokerOrderExecution:
    service = create_order_execution_service(session)
    try:
        return service.refresh_execution(execution_id)
    except AlpacaPaperClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if "not found" in message else 400, detail=message
        ) from exc


def _require_etoro_live_manual_confirmation(
    session: Session,
    execution_id: int,
    *,
    operation: str,
    request: BrokerManualActionRequest | None,
) -> None:
    repository = BrokerOrderExecutionRepository(session)
    try:
        order = repository.get(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if order.broker != "etoro" or order.account_mode != "live":
        return
    try:
        account = BrokerAccountRepository(session).get(order.broker_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="etoro_live_broker_account_missing") from exc
    if not account.manual_actions_enabled:
        raise HTTPException(status_code=400, detail="etoro_live_manual_actions_disabled")
    expected = f"CONFIRM LIVE ETORO {order.broker_account_id} {operation}"
    confirmation = (request.confirmation_text if request is not None else "").strip()
    if confirmation != expected:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "etoro_live_manual_confirmation_required",
                "required_confirmation_text": expected,
            },
        )
