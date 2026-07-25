import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution, BrokerPosition
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository


class EtoroLiveManualCloseApiTests(unittest.IsolatedAsyncioTestCase):
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
            BrokerAccountRepository(session).create(
                BrokerAccount(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    account_label="eToro live",
                    manual_actions_enabled=True,
                )
            )
            order = BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    recommendation_plan_id=101,
                    recommendation_plan_ticker="AAPL",
                    ticker="AAPL",
                    action="long",
                    side="buy",
                    order_type="market",
                    quantity=1,
                    notional_amount=25.0,
                    status="accepted",
                    client_order_id="live-close-client",
                    created_at=datetime.now(UTC),
                )
            )
            self.position_id = (
                BrokerPositionRepository(session)
                .create(
                    BrokerPosition(
                        broker_order_execution_id=order.id or 0,
                        broker_account_id="etoro-live-main",
                        broker="etoro",
                        account_mode="live",
                        recommendation_plan_id=101,
                        recommendation_plan_ticker="AAPL",
                        ticker="AAPL",
                        action="long",
                        side="buy",
                        quantity=1,
                        current_quantity=1,
                        status="open",
                        entry_order_id="etoro-order-1",
                    )
                )
                .id
            )
        finally:
            session.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_etoro_live_position_close_requires_exact_confirmation(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.post(f"/api/broker-positions/{self.position_id}/close")
            wrong = await client.post(
                f"/api/broker-positions/{self.position_id}/close",
                json={"confirmation_text": "close"},
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(
            wrong.json()["detail"]["reason"], "etoro_live_manual_confirmation_required"
        )

    async def test_etoro_live_position_close_is_fail_closed_after_confirmation(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/broker-positions/{self.position_id}/close",
                json={"confirmation_text": "CONFIRM LIVE ETORO etoro-live-main close"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "etoro_live_mutation_disabled")

    async def test_non_live_position_close_uses_existing_order_execution_service(self) -> None:
        session = Session(bind=self.engine)
        try:
            order = BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker_account_id="alpaca-paper-default",
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=102,
                    recommendation_plan_ticker="MSFT",
                    ticker="MSFT",
                    action="long",
                    side="buy",
                    order_type="market",
                    quantity=1,
                    notional_amount=100.0,
                    status="accepted",
                    client_order_id="paper-close-client",
                )
            )
            paper_position_id = (
                BrokerPositionRepository(session)
                .create(
                    BrokerPosition(
                        broker_order_execution_id=order.id or 0,
                        broker_account_id="alpaca-paper-default",
                        broker="alpaca",
                        account_mode="paper",
                        recommendation_plan_id=102,
                        recommendation_plan_ticker="MSFT",
                        ticker="MSFT",
                        action="long",
                        side="buy",
                        quantity=1,
                        current_quantity=1,
                        status="open",
                    )
                )
                .id
            )
        finally:
            session.close()

        calls: list[str] = []

        class FakeService:
            def close_position(self, ticker: str):
                calls.append(ticker)
                return {"ticker": ticker}

        with patch(
            "trade_proposer_app.api.routes.broker_positions.create_order_execution_service",
            return_value=FakeService(),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(f"/api/broker-positions/{paper_position_id}/close")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["MSFT"])


if __name__ == "__main__":
    unittest.main()
