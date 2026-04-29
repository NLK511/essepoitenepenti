from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository

router = APIRouter(prefix="/broker-positions", tags=["broker-positions"])


@router.get("", response_model=list[BrokerPosition])
async def list_broker_positions(
    run_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[BrokerPosition]:
    return BrokerPositionRepository(session).list_all(run_id=run_id, limit=limit)


@router.get("/{position_id}", response_model=BrokerPosition)
async def get_broker_position(position_id: int, session: Session = Depends(get_db_session)) -> BrokerPosition:
    try:
        return BrokerPositionRepository(session).get(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
