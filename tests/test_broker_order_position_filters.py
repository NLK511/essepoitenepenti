import unittest
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerOrderExecution, BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository


class BrokerOrderPositionFiltersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.original_auth_enabled = settings.single_user_auth_enabled
        settings.single_user_auth_enabled = False

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session
        session = Session(bind=self.engine)
        try:
            orders = BrokerOrderExecutionRepository(session)
            live = orders.create(self._order("etoro-live-main", "etoro", "live", "accepted"))
            paper = orders.create(
                self._order("alpaca-paper-default", "alpaca", "paper", "submitted")
            )
            positions = BrokerPositionRepository(session)
            positions.create(self._position(live, "open"))
            positions.create(self._position(paper, "submitted"))
        finally:
            session.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    def _order(
        self, broker_account_id: str, broker: str, account_mode: str, status: str
    ) -> BrokerOrderExecution:
        return BrokerOrderExecution(
            broker_account_id=broker_account_id,
            broker=broker,
            account_mode=account_mode,
            recommendation_plan_id=101 if broker == "etoro" else 102,
            recommendation_plan_ticker="AAPL",
            run_id=1,
            job_id=1,
            ticker="AAPL",
            action="long",
            side="buy",
            order_type="market",
            quantity=1,
            notional_amount=25.0,
            status=status,
            broker_order_id=f"{broker_account_id}-order",
            client_order_id=f"{broker_account_id}-client",
            created_at=datetime.now(timezone.utc),
        )

    def _position(self, order: BrokerOrderExecution, status: str) -> BrokerPosition:
        return BrokerPosition(
            broker_order_execution_id=order.id or 0,
            broker_account_id=order.broker_account_id,
            broker=order.broker,
            account_mode=order.account_mode,
            recommendation_plan_id=order.recommendation_plan_id,
            recommendation_plan_ticker=order.recommendation_plan_ticker,
            run_id=order.run_id,
            job_id=order.job_id,
            ticker=order.ticker,
            action=order.action,
            side=order.side,
            quantity=1,
            current_quantity=1,
            status=status,
            entry_order_id=order.broker_order_id,
        )

    async def test_broker_order_filters_by_account_broker_mode_and_status(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            by_account = await client.get("/api/broker-orders?broker_account_id=etoro-live-main")
            by_mode = await client.get("/api/broker-orders?account_mode=live")
            by_broker_status = await client.get("/api/broker-orders?broker=alpaca&status=submitted")

        self.assertEqual(len(by_account.json()), 1)
        self.assertEqual(by_account.json()[0]["broker_account_id"], "etoro-live-main")
        self.assertEqual(len(by_mode.json()), 1)
        self.assertEqual(by_mode.json()[0]["account_mode"], "live")
        self.assertEqual(len(by_broker_status.json()), 1)
        self.assertEqual(by_broker_status.json()[0]["broker"], "alpaca")

    async def test_broker_position_filters_by_account_broker_mode_and_status(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/broker-positions?broker_account_id=etoro-live-main&broker=etoro&account_mode=live&status=open"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["broker_account_id"], "etoro-live-main")
        self.assertEqual(payload[0]["status"], "open")


if __name__ == "__main__":
    unittest.main()
