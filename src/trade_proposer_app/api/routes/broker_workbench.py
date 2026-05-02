from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.broker_reconciliation import BrokerReconciliationService

router = APIRouter(prefix="/broker-workbench", tags=["broker-workbench"])


@router.get("")
async def get_broker_workbench(
    run_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return BrokerReconciliationService(session).build_workbench(run_id=run_id, limit=limit)
