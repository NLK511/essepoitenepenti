import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerAccount, RecommendationPlan
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import BrokerCapabilities, FakeBrokerAdapter
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class StaticAdapterFactory:
    def __init__(self) -> None:
        self.adapters: dict[str, FakeBrokerAdapter] = {}

    def add(self, broker_account_id: str) -> None:
        self.adapters[broker_account_id] = FakeBrokerAdapter(
            capabilities=BrokerCapabilities(broker="etoro", account_mode="live")
        )

    def for_account_id(self, broker_account_id: str):
        return self.adapters[broker_account_id]


class EtoroLiveGatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.safety = BrokerAccountSafetyRepository(self.session)
        self.factory = StaticAdapterFactory()
        self.settings.set_order_execution_config(enabled=True, notional_per_plan=25.0)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _plan(self) -> RecommendationPlan:
        return RecommendationPlan(
            id=101,
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=80.0,
            entry_price_low=24.0,
            entry_price_high=26.0,
            stop_loss=20.0,
            take_profit=30.0,
            computed_at=datetime.now(timezone.utc),
        )

    def _account(
        self,
        *,
        risk_settings: dict[str, object] | None = None,
        validation_evidence: dict[str, object] | None = None,
    ) -> None:
        self.accounts.create(
            BrokerAccount(
                broker_account_id="etoro-live-main",
                broker="etoro",
                account_mode="live",
                account_label="eToro live",
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=25.0,
                symbol_allowlist=["AAPL"],
                validation_status="validated",
                validation_evidence=validation_evidence
                or {"permission_scope": "real", "permissions": ["read", "real_trading"]},
                risk_settings=risk_settings or {},
            )
        )
        self.factory.add("etoro-live-main")
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=1000.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

    def _service(self, *, latest_price_lookup=None) -> MultiBrokerExecutionService:
        return MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
            safety=self.safety,
            latest_price_lookup=latest_price_lookup,
        )

    def test_live_defaults_block_real_submission(self) -> None:
        self._account()

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "etoro_live_trading_disabled")
        self.assertEqual(self.factory.adapters["etoro-live-main"].orders, {})

    def test_live_requires_acknowledgement_and_demo_validation(self) -> None:
        self._account(risk_settings={"live_trading_enabled": True})
        missing_ack = self._service().execute_plans([self._plan()], run_id=2, job_id=2).orders[0]
        self.assertEqual(missing_ack.error_message, "etoro_live_acknowledgement_missing")

        self.session.close()
        self.engine.dispose()
        self.setUp()
        self._account(risk_settings={"live_trading_enabled": True, "live_acknowledged": True})
        missing_demo = self._service().execute_plans([self._plan()], run_id=3, job_id=2).orders[0]
        self.assertEqual(missing_demo.error_message, "etoro_demo_validation_missing")

    def test_demo_override_does_not_bypass_permission_or_drawdown_gates(self) -> None:
        self._account(
            risk_settings={
                "live_trading_enabled": True,
                "live_acknowledged": True,
                "demo_validation_override": True,
            },
            validation_evidence={
                "permission_scope": "demo",
                "permissions": ["read", "demo_trading"],
            },
        )

        order = self._service().execute_plans([self._plan()], run_id=4, job_id=2).orders[0]

        self.assertEqual(order.status, "skipped")
        self.assertEqual(order.error_message, "etoro_permission_missing")

    def test_live_shadow_persists_would_submit_without_adapter_call(self) -> None:
        self._account(
            risk_settings={
                "live_shadow_enabled": True,
                "live_trading_enabled": True,
                "live_acknowledged": True,
                "demo_validation_artifact_id": "demo-artifact-1",
            }
        )

        order = self._service().execute_plans([self._plan()], run_id=5, job_id=2).orders[0]

        self.assertEqual(order.status, "skipped")
        self.assertEqual(order.error_message, "etoro_live_shadow_would_submit")
        self.assertTrue(order.request_payload["would_submit"])
        self.assertEqual(self.factory.adapters["etoro-live-main"].orders, {})

    def test_price_outside_entry_tolerance_blocks_live_candidate(self) -> None:
        self._account(
            risk_settings={
                "live_trading_enabled": True,
                "live_acknowledged": True,
                "demo_validation_artifact_id": "demo-artifact-1",
                "max_entry_slippage_pct": 1.0,
            }
        )

        order = (
            self._service(latest_price_lookup=lambda symbol: 30.0)
            .execute_plans([self._plan()], run_id=6, job_id=2)
            .orders[0]
        )

        self.assertEqual(order.status, "skipped")
        self.assertEqual(order.error_message, "etoro_price_outside_entry_tolerance")
        self.assertEqual(self.factory.adapters["etoro-live-main"].orders, {})

    def test_missing_latest_price_blocks_when_tolerance_required(self) -> None:
        self._account(
            risk_settings={
                "live_trading_enabled": True,
                "live_acknowledged": True,
                "demo_validation_artifact_id": "demo-artifact-1",
                "max_entry_slippage_pct": 1.0,
            }
        )

        order = (
            self._service(latest_price_lookup=lambda symbol: None)
            .execute_plans([self._plan()], run_id=7, job_id=2)
            .orders[0]
        )

        self.assertEqual(order.status, "skipped")
        self.assertEqual(order.error_message, "etoro_price_unavailable")
        self.assertEqual(self.factory.adapters["etoro-live-main"].orders, {})


if __name__ == "__main__":
    unittest.main()
