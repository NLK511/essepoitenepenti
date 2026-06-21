import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerAccount, RecommendationPlan
from trade_proposer_app.persistence.models import Base, BrokerAccountRecord
from trade_proposer_app.repositories.broker_account_safety import BrokerAccountSafetyRepository
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import BrokerCapabilities, FakeBrokerAdapter
from trade_proposer_app.services.brokers.adapter import BrokerOrderResult
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class AmbiguousSubmitAdapter(FakeBrokerAdapter):
    def submit_order(self, request):
        return BrokerOrderResult.ambiguous(
            operation="submit_order",
            client_request_id=request.client_order_id,
            message="timeout after submit",
        )


class StaticAdapterFactory:
    def __init__(self, adapter=None) -> None:
        self.adapter = adapter or FakeBrokerAdapter(
            capabilities=BrokerCapabilities(broker="etoro", account_mode="live")
        )

    def for_account_id(self, broker_account_id: str):
        return self.adapter


class BrokerAccountSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.safety = BrokerAccountSafetyRepository(self.session)
        self.settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)
        self.accounts.create(
            BrokerAccount(
                broker_account_id="etoro-live-main",
                broker="etoro",
                account_mode="live",
                account_label="live",
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=1000.0,
                validation_evidence={"permission_scope": "real", "permissions": ["real_trading"]},
                risk_settings={
                    "live_trading_enabled": True,
                    "live_acknowledged": True,
                    "demo_validation_artifact_id": "test-demo-artifact",
                },
            )
        )

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
            entry_price_low=99.0,
            entry_price_high=101.0,
            stop_loss=95.0,
            take_profit=110.0,
            computed_at=datetime.now(timezone.utc),
        )

    def _service(self, adapter=None) -> MultiBrokerExecutionService:
        return MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=StaticAdapterFactory(adapter=adapter),
            safety=self.safety,
        )

    def test_live_account_without_drawdown_baseline_is_warmup_blocked(self) -> None:
        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_drawdown_evidence_unavailable")

    def test_trusted_drawdown_baseline_allows_submission(self) -> None:
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=1000.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "accepted")

    def test_active_circuit_breaker_blocks_account(self) -> None:
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=1000.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )
        self.safety.activate_circuit_breaker("etoro-live-main", reason="rate_limit")

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "broker_circuit_breaker_active")

    def test_ambiguous_submit_sets_needs_review_and_circuit_breaker(self) -> None:
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=1000.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

        outcome = self._service(adapter=AmbiguousSubmitAdapter()).execute_plans(
            [self._plan()], run_id=1, job_id=2
        )

        self.assertEqual(outcome.orders[0].status, "needs_review")
        breaker = self.safety.get_circuit_breaker("etoro-live-main")
        self.assertTrue(breaker.active)
        self.assertEqual(breaker.reason, "ambiguous_submit_order")

    def test_drawdown_limit_blocks_when_equity_below_configured_threshold(self) -> None:
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=900.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )
        account_record = self.session.get(BrokerAccountRecord, "etoro-live-main")
        account_record.risk_settings_json = '{"max_daily_drawdown_usd": 50}'
        self.session.commit()

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_daily_drawdown_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
