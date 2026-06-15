from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.services.builders import create_order_execution_service

router = APIRouter(prefix="/broker-positions", tags=["broker-positions"])


class BrokerPositionCloseRequest(BaseModel):
    confirmation_text: str = ""


@router.get("", response_model=list[BrokerPosition])
async def list_broker_positions(
    run_id: int | None = Query(default=None),
    broker_account_id: str | None = Query(default=None),
    broker: str | None = Query(default=None),
    account_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[BrokerPosition]:
    repository = BrokerPositionRepository(session)
    if any([run_id is not None, broker_account_id, broker, account_mode, status]):
        return repository.list_filtered(
            run_id=run_id,
            broker_account_id=broker_account_id,
            broker=broker,
            account_mode=account_mode,
            status=status,
            limit=limit,
        )
    return repository.list_all(run_id=run_id, limit=limit)


@router.get("/{position_id}", response_model=BrokerPosition)
async def get_broker_position(
    position_id: int, session: Session = Depends(get_db_session)
) -> BrokerPosition:
    try:
        return BrokerPositionRepository(session).get(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{position_id}/close")
async def close_broker_position(
    position_id: int,
    request: BrokerPositionCloseRequest | None = None,
    session: Session = Depends(get_db_session),
) -> object:
    position = _get_position_or_404(session, position_id)
    if position.broker == "etoro" and position.account_mode == "live":
        _require_etoro_live_position_confirmation(session, position, request=request)
        raise HTTPException(status_code=400, detail="etoro_live_mutation_disabled")
    return create_order_execution_service(session).close_position(position.ticker)


def _get_position_or_404(session: Session, position_id: int) -> BrokerPosition:
    try:
        return BrokerPositionRepository(session).get(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _require_etoro_live_position_confirmation(
    session: Session,
    position: BrokerPosition,
    *,
    request: BrokerPositionCloseRequest | None,
) -> None:
    try:
        account = BrokerAccountRepository(session).get(position.broker_account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="etoro_live_broker_account_missing") from exc
    if not account.manual_actions_enabled:
        raise HTTPException(status_code=400, detail="etoro_live_manual_actions_disabled")
    expected = f"CONFIRM LIVE ETORO {position.broker_account_id} close"
    confirmation = (request.confirmation_text if request is not None else "").strip()
    if confirmation != expected:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "etoro_live_manual_confirmation_required",
                "required_confirmation_text": expected,
            },
        )
