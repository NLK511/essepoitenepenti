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
from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository


class FakeOrderExecutionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def cancel_execution(self, execution_id: int) -> BrokerOrderExecution:
        order = BrokerOrderExecutionRepository(self.session).get(execution_id)
        order.status = "cancel_requested"
        return order

    def resubmit_execution(self, execution_id: int) -> BrokerOrderExecution:
        order = BrokerOrderExecutionRepository(self.session).get(execution_id)
        order.status = "resubmit_requested"
        return order


class EtoroLiveManualActionsApiTests(unittest.IsolatedAsyncioTestCase):
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
                    enabled=True,
                    manual_actions_enabled=True,
                )
            )
            self.execution_id = (
                BrokerOrderExecutionRepository(session)
                .create(
                    BrokerOrderExecution(
                        broker_account_id="etoro-live-main",
                        broker="etoro",
                        account_mode="live",
                        recommendation_plan_id=101,
                        recommendation_plan_ticker="AAPL",
                        run_id=1,
                        job_id=1,
                        ticker="AAPL",
                        action="long",
                        side="buy",
                        order_type="market",
                        quantity=1,
                        notional_amount=25.0,
                        status="accepted",
                        client_order_id="live-order-1",
                        created_at=datetime.now(UTC),
                    )
                )
                .id
            )
        finally:
            session.close()
        self.service_patcher = patch(
            "trade_proposer_app.api.routes.broker_orders.create_order_execution_service",
            side_effect=lambda session: FakeOrderExecutionService(session),
        )
        self.service_patcher.start()

    def tearDown(self) -> None:
        self.service_patcher.stop()
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_etoro_live_cancel_requires_explicit_confirmation_text(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.post(f"/api/broker-orders/{self.execution_id}/cancel")
            wrong = await client.post(
                f"/api/broker-orders/{self.execution_id}/cancel",
                json={"confirmation_text": "cancel it"},
            )
            accepted = await client.post(
                f"/api/broker-orders/{self.execution_id}/cancel",
                json={"confirmation_text": "CONFIRM LIVE ETORO etoro-live-main cancel"},
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "cancel_requested")

    async def test_etoro_live_resubmit_is_blocked_when_manual_actions_disabled(self) -> None:
        session = Session(bind=self.engine)
        try:
            BrokerAccountRepository(session).update_controls(
                "etoro-live-main", {"manual_actions_enabled": False}
            )
        finally:
            session.close()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/broker-orders/{self.execution_id}/resubmit",
                json={"confirmation_text": "CONFIRM LIVE ETORO etoro-live-main resubmit"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "etoro_live_manual_actions_disabled")


if __name__ == "__main__":
    unittest.main()
