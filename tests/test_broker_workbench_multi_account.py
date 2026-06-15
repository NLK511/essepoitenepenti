import unittest

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository


class BrokerWorkbenchMultiAccountTests(unittest.IsolatedAsyncioTestCase):
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
            SettingsRepository(session).set_global_broker_risk_caps(
                max_live_open_notional_usd=250.0,
                max_live_order_count_per_day=1,
            )
            accounts = BrokerAccountRepository(session)
            accounts.create(
                BrokerAccount(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    account_label="eToro live",
                    enabled=True,
                    validation_evidence={"x-user-key": "secret", "permission_scope": "real"},
                    risk_settings={"live_trading_enabled": False, "x_user_key": "secret"},
                )
            )
            accounts.upsert_credentials("etoro-live-main", {"x_user_key": "secret"})
            safety = BrokerAccountSafetyRepository(session)
            safety.record_drawdown_baseline(
                "etoro-live-main",
                current_equity=1000.0,
                daily_high_water_equity=1000.0,
                total_high_water_equity=1000.0,
                broker_timezone="UTC",
                trusted=True,
            )
            safety.activate_circuit_breaker("etoro-live-main", reason="operator_test")
            orders = BrokerOrderExecutionRepository(session)
            orders.create(
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
                    client_order_id="etoro-live-client",
                )
            )
            orders.create(
                BrokerOrderExecution(
                    broker_account_id="alpaca-paper-default",
                    broker="alpaca",
                    account_mode="paper",
                    recommendation_plan_id=102,
                    recommendation_plan_ticker="MSFT",
                    ticker="MSFT",
                    action="long",
                    side="buy",
                    order_type="limit",
                    quantity=1,
                    notional_amount=100.0,
                    status="submitted",
                    client_order_id="alpaca-paper-client",
                )
            )
        finally:
            session.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_workbench_filters_orders_by_broker_account_mode_and_status(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/broker-workbench?broker_account_id=etoro-live-main&account_mode=live&status=accepted"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["broker_orders"], 1)
        self.assertEqual(payload["broker_orders"][0]["broker_account_id"], "etoro-live-main")
        self.assertEqual(payload["broker_orders"][0]["account_mode"], "live")
        self.assertEqual(payload["broker_orders"][0]["status"], "accepted")

    async def test_workbench_includes_redacted_broker_accounts_and_global_live_caps(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/broker-workbench")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("broker_accounts", payload)
        self.assertEqual(payload["broker_accounts"][0]["broker_account_id"], "etoro-live-main")
        self.assertEqual(payload["broker_accounts"][0]["mode_badge"], "LIVE")
        self.assertTrue(payload["broker_accounts"][0]["has_credentials"])
        self.assertTrue(payload["broker_accounts"][0]["circuit_breaker"]["active"])
        self.assertTrue(payload["broker_accounts"][0]["drawdown"]["trusted"])
        self.assertEqual(
            payload["global_broker_risk_caps"]["global_max_live_open_notional_usd"], 250.0
        )
        self.assertEqual(payload["global_live_summary"]["enabled_live_account_count"], 1)
        self.assertNotIn("secret", str(payload))
        self.assertEqual(payload["broker_accounts"][0]["risk_settings"]["x_user_key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
