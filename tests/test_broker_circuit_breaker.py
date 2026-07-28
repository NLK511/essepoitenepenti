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
from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerOrderResult,
    FakeBrokerAdapter,
)
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class RateLimitedAdapter(FakeBrokerAdapter):
    def submit_order(self, request):
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.RATE_LIMITED,
            operation="submit_order",
            client_request_id=request.client_order_id,
            message="rate limit",
            retry_after_seconds=None,
        )


class StaticAdapterFactory:
    def __init__(self, adapters: dict[str, FakeBrokerAdapter]) -> None:
        self.adapters = adapters

    def for_account_id(self, broker_account_id: str):
        return self.adapters[broker_account_id]


class BrokerCircuitBreakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.safety = BrokerAccountSafetyRepository(self.session)
        self.settings.set_order_execution_config(enabled=True, broker="alpaca", account_mode="paper", notional_per_plan=1000.0)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _account(self, broker_account_id: str) -> None:
        self.accounts.create(
            BrokerAccount(
                broker_account_id=broker_account_id,
                broker="etoro",
                account_mode="live",
                account_label=broker_account_id,
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
        self.safety.record_drawdown_baseline(
            broker_account_id,
            current_equity=1000.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

    def _plan(self, plan_id: int = 101) -> RecommendationPlan:
        return RecommendationPlan(
            id=plan_id,
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

    def test_rate_limit_response_activates_circuit_breaker(self) -> None:
        self._account("etoro-live-main")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=StaticAdapterFactory({"etoro-live-main": RateLimitedAdapter()}),
            safety=self.safety,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "failed")
        breaker = self.safety.get_circuit_breaker("etoro-live-main")
        self.assertTrue(breaker.active)
        self.assertEqual(breaker.reason, "rate_limited_submit_order")

    def test_manual_clear_requires_reason_and_trusted_drawdown_state(self) -> None:
        self._account("etoro-live-main")
        self.safety.activate_circuit_breaker("etoro-live-main", reason="rate_limit")

        with self.assertRaises(ValueError):
            self.safety.clear_circuit_breaker("etoro-live-main", reason="")
        cleared = self.safety.clear_circuit_breaker(
            "etoro-live-main",
            reason="operator reviewed broker state",
            require_trusted_drawdown=True,
        )

        self.assertFalse(cleared.active)
        self.assertEqual(cleared.clear_reason, "operator reviewed broker state")
        self.assertEqual(cleared.reason, "rate_limit")

    def test_clear_with_trusted_snapshot_requirement_blocks_missing_baseline(self) -> None:
        self.accounts.create(
            BrokerAccount(
                broker_account_id="etoro-live-no-baseline",
                broker="etoro",
                account_mode="live",
                account_label="missing",
                enabled=True,
                autonomous_execution_enabled=True,
            )
        )
        self.safety.activate_circuit_breaker("etoro-live-no-baseline", reason="unknown")

        with self.assertRaisesRegex(ValueError, "trusted drawdown"):
            self.safety.clear_circuit_breaker(
                "etoro-live-no-baseline",
                reason="reviewed",
                require_trusted_drawdown=True,
            )

    def test_one_account_breaker_does_not_block_another_account(self) -> None:
        self._account("etoro-live-a")
        self._account("etoro-live-b")
        self.safety.activate_circuit_breaker("etoro-live-a", reason="rate_limit")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=StaticAdapterFactory(
                {"etoro-live-a": FakeBrokerAdapter(), "etoro-live-b": FakeBrokerAdapter()}
            ),
            safety=self.safety,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)
        by_account = {order.broker_account_id: order for order in outcome.orders}

        self.assertEqual(by_account["etoro-live-a"].error_message, "broker_circuit_breaker_active")
        self.assertEqual(by_account["etoro-live-b"].status, "accepted")


if __name__ == "__main__":
    unittest.main()
