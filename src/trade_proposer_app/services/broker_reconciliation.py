from __future__ import annotations

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.builders import create_order_execution_service
from trade_proposer_app.services.risk_management import BrokerRiskManager
from trade_proposer_app.services.settings_domains import SettingsDomainService


class BrokerReconciliationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.orders = BrokerOrderExecutionRepository(session)
        self.positions = BrokerPositionRepository(session)
        self.settings = SettingsRepository(session)
        self.settings_domains = SettingsDomainService(repository=self.settings)
        self.halt_events = RiskHaltEventRepository(session)

    def build_workbench(self, *, run_id: int | None = None, limit: int = 50) -> dict[str, object]:
        listed_orders = self.orders.list_by_run(run_id=run_id, limit=limit) if run_id is not None else self.orders.list_all(limit=limit)
        listed_positions = self.positions.list_all(run_id=run_id, limit=limit)
        risk = BrokerRiskManager(self.settings, self.positions, self.halt_events).assess()
        halt_events = self.halt_events.list_latest(limit=10)
        return {
            "broker_orders": [order.model_dump(mode="json") for order in listed_orders],
            "broker_positions": [position.model_dump(mode="json") for position in listed_positions],
            "risk": risk.model_dump(mode="json"),
            "risk_halt_events": [event.model_dump(mode="json") for event in halt_events],
            "broker_sync_state": self.settings_domains.broker_sync_state().to_dict(),
            "counts": {
                "broker_orders": len(listed_orders),
                "broker_positions": len(listed_positions),
            },
        }

    def sync_open_orders(self, *, limit: int = 200):
        return create_order_execution_service(self.session).sync_open_executions(limit=limit)
