from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.risk_management import BrokerRiskManager

router = APIRouter(prefix="/broker-workbench", tags=["broker-workbench"])


@router.get("")
async def get_broker_workbench(
    run_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    orders = BrokerOrderExecutionRepository(session)
    positions = BrokerPositionRepository(session)
    listed_orders = orders.list_by_run(run_id=run_id, limit=limit) if run_id is not None else orders.list_all(limit=limit)
    listed_positions = positions.list_all(run_id=run_id, limit=limit)
    settings = SettingsRepository(session)
    risk = BrokerRiskManager(settings, positions).assess()
    halt_events = RiskHaltEventRepository(session).list_latest(limit=10)
    return {
        "broker_orders": [order.model_dump(mode="json") for order in listed_orders],
        "broker_positions": [position.model_dump(mode="json") for position in listed_positions],
        "risk": risk.model_dump(mode="json"),
        "risk_halt_events": [event.model_dump(mode="json") for event in halt_events],
        "settings": [setting.model_dump(mode="json") for setting in settings.list_settings()],
        "counts": {
            "broker_orders": len(listed_orders),
            "broker_positions": len(listed_positions),
        },
    }
