from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.risk_management import BrokerRiskManager


def test_fractional_position_units_round_trip_and_drive_open_notional() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        position = BrokerPositionRepository(session).create(
            BrokerPosition(
                broker_order_execution_id=1,
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                recommendation_plan_id=1,
                recommendation_plan_ticker="PYPL",
                ticker="PYPL",
                action="long",
                side="buy",
                quantity=1,
                current_quantity=1,
                unit_quantity=0.444919,
                current_unit_quantity=0.444919,
                status="open",
                entry_order_id="3567506772",
                entry_avg_price=56.18,
            )
        )

        loaded = BrokerPositionRepository(session).get(position.id or 0)
        assessment = BrokerRiskManager(
            SettingsRepository(session),
            BrokerPositionRepository(session),
        ).assess()

        assert loaded.unit_quantity == 0.444919
        assert loaded.current_unit_quantity == 0.444919
        assert assessment.metrics["open_notional_usd"] == 24.9955
    finally:
        session.close()
        engine.dispose()
