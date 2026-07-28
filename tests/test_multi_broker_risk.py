import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution, RecommendationPlan
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import BrokerCapabilities, FakeBrokerAdapter
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class StaticAdapterFactory:
    def __init__(self) -> None:
        self.adapters: dict[str, FakeBrokerAdapter] = {}

    def add(self, broker_account_id: str, broker: str = "alpaca") -> None:
        self.adapters[broker_account_id] = FakeBrokerAdapter(
            capabilities=BrokerCapabilities(broker=broker, account_mode="live")
        )

    def for_account_id(self, broker_account_id: str):
        return self.adapters[broker_account_id]


class MultiBrokerRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.factory = StaticAdapterFactory()
        self.settings.set_order_execution_config(enabled=True, broker="alpaca", account_mode="paper", notional_per_plan=1000.0)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _plan(self, ticker: str = "AAPL") -> RecommendationPlan:
        return RecommendationPlan(
            id=101,
            ticker=ticker,
            horizon=StrategyHorizon.ONE_WEEK,
            action="long",
            confidence_percent=80.0,
            entry_price_low=99.0,
            entry_price_high=101.0,
            stop_loss=95.0,
            take_profit=110.0,
            computed_at=datetime.now(timezone.utc),
        )

    def _account(self, broker_account_id: str = "etoro-live-main", **overrides: object) -> None:
        values = {
            "broker_account_id": broker_account_id,
            "broker": "etoro",
            "account_mode": "live",
            "account_label": broker_account_id,
            "enabled": True,
            "autonomous_execution_enabled": True,
            "notional_cap_usd": 1000.0,
            "validation_evidence": {"permission_scope": "real", "permissions": ["real_trading"]},
            "risk_settings": {
                "live_trading_enabled": True,
                "live_acknowledged": True,
                "demo_validation_artifact_id": "test-demo-artifact",
            },
        }
        values.update(overrides)
        self.accounts.create(BrokerAccount(**values))
        self.factory.add(broker_account_id, broker=str(values["broker"]))

    def _service(self) -> MultiBrokerExecutionService:
        return MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

    def _existing_order(
        self,
        *,
        broker_account_id: str = "etoro-live-main",
        ticker: str = "MSFT",
        status: str = "accepted",
        notional: float = 500.0,
        plan_id: int = 900,
    ) -> None:
        self.executions.create(
            BrokerOrderExecution(
                broker_account_id=broker_account_id,
                broker="etoro",
                account_mode="live",
                recommendation_plan_id=plan_id,
                recommendation_plan_ticker=ticker,
                run_id=77 + plan_id,
                job_id=1,
                ticker=ticker,
                action="long",
                side="buy",
                order_type="market",
                quantity=1,
                notional_amount=notional,
                status=status,
                client_order_id=f"existing-{broker_account_id}-{plan_id}",
            )
        )

    def test_position_notional_cap_blocks_candidate_before_submit(self) -> None:
        self._account(max_position_notional_usd=250.0)

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_position_notional_limit_exceeded")
        self.assertEqual(len(self.factory.adapters["etoro-live-main"].orders), 0)

    def test_open_position_and_notional_caps_include_existing_account_exposure(self) -> None:
        self._account(max_open_positions=1, max_open_notional_usd=1200.0)
        self._existing_order(notional=500.0)

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_open_position_limit_exceeded")

    def test_same_ticker_limit_blocks_only_matching_ticker(self) -> None:
        self._account(max_same_ticker_open_positions=1)
        self._existing_order(ticker="AAPL", notional=500.0)

        blocked = self._service().execute_plans([self._plan("AAPL")], run_id=1, job_id=2)
        allowed = self._service().execute_plans([self._plan("MSFT")], run_id=2, job_id=2)

        self.assertEqual(blocked.orders[0].error_message, "risk_same_ticker_limit_exceeded")
        self.assertEqual(allowed.orders[0].status, "accepted")

    def test_symbol_allowlist_and_denylist_are_enforced_per_account(self) -> None:
        self._account(symbol_allowlist=["MSFT"], symbol_denylist=["TSLA"])

        not_allowed = self._service().execute_plans([self._plan("AAPL")], run_id=1, job_id=2)
        denied = self._service().execute_plans([self._plan("TSLA")], run_id=2, job_id=2)
        allowed = self._service().execute_plans([self._plan("MSFT")], run_id=3, job_id=2)

        self.assertEqual(not_allowed.orders[0].error_message, "broker_symbol_not_allowlisted")
        self.assertEqual(denied.orders[0].error_message, "broker_symbol_denied")
        self.assertEqual(allowed.orders[0].status, "accepted")

    def test_daily_order_count_limit_blocks_per_account(self) -> None:
        self._account(risk_settings={"max_daily_order_count": 1})
        self._existing_order(status="accepted", plan_id=901)

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_daily_order_count_limit_exceeded")

    def test_global_live_daily_order_count_cap_blocks_live_accounts(self) -> None:
        self.settings.set_global_broker_risk_caps(max_live_order_count_per_day=1)
        self._account("etoro-live-main")
        self._existing_order(broker_account_id="etoro-live-main", status="accepted", plan_id=902)

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(
            outcome.orders[0].error_message, "risk_global_live_order_count_limit_exceeded"
        )

    def test_global_live_open_notional_cap_blocks_live_accounts(self) -> None:
        self.settings.set_global_broker_risk_caps(max_live_open_notional_usd=1200.0)
        self._account("etoro-live-main")
        self._account("etoro-live-second")
        self._existing_order(broker_account_id="etoro-live-main", notional=500.0)

        outcome = self._service().execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.summary["submitted_order_count"], 0)
        self.assertEqual(
            {order.error_message for order in outcome.orders},
            {"risk_global_live_notional_limit_exceeded"},
        )


if __name__ == "__main__":
    unittest.main()
