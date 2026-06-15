import unittest
from datetime import datetime, timezone

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
from trade_proposer_app.repositories.settings import SettingsRepository


class BrokerRiskApiMultiAccountTests(unittest.IsolatedAsyncioTestCase):
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
                max_live_open_notional_usd=1000.0,
                max_live_daily_drawdown_usd=50.0,
                max_live_daily_drawdown_pct=5.0,
                max_live_order_count_per_day=2,
            )
            accounts = BrokerAccountRepository(session)
            accounts.create(
                BrokerAccount(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    account_label="eToro live",
                    enabled=True,
                    notional_cap_usd=25.0,
                )
            )
            accounts.create(
                BrokerAccount(
                    broker_account_id="alpaca-paper-default",
                    broker="alpaca",
                    account_mode="paper",
                    account_label="Alpaca paper",
                    enabled=True,
                )
            )
            BrokerOrderExecutionRepository(session).create(
                BrokerOrderExecution(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    recommendation_plan_id=101,
                    ticker="AAPL",
                    recommendation_plan_ticker="AAPL",
                    run_id=1,
                    job_id=1,
                    action="long",
                    side="buy",
                    order_type="market",
                    quantity=1,
                    notional_amount=25.0,
                    status="accepted",
                    client_order_id="live-order-1",
                    created_at=datetime.now(timezone.utc),
                )
            )
        finally:
            session.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_get_global_live_caps_and_aggregate_risk_summary(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/risk/broker-caps")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["caps"]["global_max_live_open_notional_usd"], 1000.0)
        self.assertEqual(payload["caps"]["global_max_live_order_count_per_day"], 2)
        self.assertEqual(payload["live_summary"]["enabled_live_account_count"], 1)
        self.assertEqual(payload["live_summary"]["active_live_open_notional_usd"], 25.0)
        self.assertEqual(payload["live_summary"]["live_order_count_today"], 1)

    async def test_update_global_live_caps_round_trips(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/risk/broker-caps",
                json={
                    "global_max_live_open_notional_usd": 250.0,
                    "global_max_live_daily_drawdown_usd": 10.0,
                    "global_max_live_daily_drawdown_pct": 2.5,
                    "global_max_live_order_count_per_day": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        caps = response.json()["caps"]
        self.assertEqual(caps["global_max_live_open_notional_usd"], 250.0)
        self.assertEqual(caps["global_max_live_daily_drawdown_usd"], 10.0)
        self.assertEqual(caps["global_max_live_daily_drawdown_pct"], 2.5)
        self.assertEqual(caps["global_max_live_order_count_per_day"], 1)


if __name__ == "__main__":
    unittest.main()
