import unittest
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import BrokerAccount
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository


class BrokerAccountsApiTests(unittest.IsolatedAsyncioTestCase):
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
            accounts = BrokerAccountRepository(session)
            accounts.create(
                BrokerAccount(
                    broker_account_id="etoro-live-main",
                    broker="etoro",
                    account_mode="live",
                    account_label="eToro live",
                    enabled=True,
                    autonomous_execution_enabled=False,
                    credential_reference="broker_account:etoro-live-main",
                    validation_status="validated",
                    validation_evidence={"x-user-key": "secret", "permission_scope": "real"},
                    risk_settings={"live_trading_enabled": False, "x_user_key": "secret"},
                )
            )
            accounts.upsert_credentials(
                "etoro-live-main", {"x_user_key": "secret", "api_key": "api"}
            )
            BrokerAccountSafetyRepository(session).record_drawdown_baseline(
                "etoro-live-main",
                current_equity=1000.0,
                daily_high_water_equity=1100.0,
                total_high_water_equity=1200.0,
                broker_timezone="UTC",
                trusted=True,
                baseline_source="test",
            )
        finally:
            session.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.single_user_auth_enabled = self.original_auth_enabled
        self.engine.dispose()

    async def test_lists_accounts_with_redacted_secret_state_and_live_badges(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/broker-accounts")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["accounts"][0]["broker_account_id"], "etoro-live-main")
        self.assertEqual(payload["accounts"][0]["mode_badge"], "LIVE")
        self.assertNotIn("secret", str(payload))
        self.assertEqual(payload["accounts"][0]["validation_evidence"]["x-user-key"], "[REDACTED]")
        self.assertEqual(payload["accounts"][0]["risk_settings"]["x_user_key"], "[REDACTED]")

    async def test_update_controls_endpoint_updates_halt_allowlist_and_live_risk_settings(
        self,
    ) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/broker-accounts/etoro-live-main",
                json={
                    "halt_enabled": True,
                    "halt_reason": "operator pause",
                    "symbol_allowlist": ["aapl", "msft"],
                    "notional_cap_usd": 25.0,
                    "risk_settings": {
                        "live_acknowledged": True,
                        "live_trading_enabled": False,
                        "x_user_key": "secret",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["halt_enabled"])
        self.assertEqual(payload["halt_reason"], "operator pause")
        self.assertEqual(payload["symbol_allowlist"], ["AAPL", "MSFT"])
        self.assertEqual(payload["notional_cap_usd"], 25.0)
        self.assertTrue(payload["risk_settings"]["live_acknowledged"])
        self.assertEqual(payload["risk_settings"]["x_user_key"], "[REDACTED]")
        self.assertNotIn("secret", str(payload))

    async def test_record_demo_validation_artifact_updates_live_gate_evidence(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/broker-accounts/etoro-live-main/demo-validation-artifact",
                json={
                    "artifact_id": "demo-validation-2026-06-06",
                    "notes": "demo open/close reconciled",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["risk_settings"]["demo_validation_artifact_id"],
            "demo-validation-2026-06-06",
        )
        self.assertEqual(
            payload["risk_settings"]["demo_validation_notes"], "demo open/close reconciled"
        )
        self.assertIn("demo_validation_recorded_at", payload["risk_settings"])

    async def test_record_demo_validation_artifact_requires_artifact_id(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/broker-accounts/etoro-live-main/demo-validation-artifact",
                json={"artifact_id": ""},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "demo validation artifact id is required")

    async def test_safety_endpoint_exposes_drawdown_and_circuit_breaker(self) -> None:
        session = Session(bind=self.engine)
        try:
            BrokerAccountSafetyRepository(session).activate_circuit_breaker(
                "etoro-live-main", reason="test_breaker"
            )
        finally:
            session.close()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/broker-accounts/etoro-live-main/safety")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["circuit_breaker"]["active"])
        self.assertEqual(payload["circuit_breaker"]["reason"], "test_breaker")
        self.assertEqual(payload["drawdown"]["current_equity"], 1000.0)
        self.assertTrue(payload["drawdown"]["trusted"])

    async def test_clear_circuit_breaker_requires_reason(self) -> None:
        session = Session(bind=self.engine)
        try:
            BrokerAccountSafetyRepository(session).activate_circuit_breaker(
                "etoro-live-main", reason="test_breaker"
            )
        finally:
            session.close()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            rejected = await client.post(
                "/api/broker-accounts/etoro-live-main/circuit-breaker/clear", json={"reason": ""}
            )
            accepted = await client.post(
                "/api/broker-accounts/etoro-live-main/circuit-breaker/clear",
                json={"reason": "operator checked latest eToro snapshot"},
            )

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.json()["active"])


if __name__ == "__main__":
    unittest.main()
