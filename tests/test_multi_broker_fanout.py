import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerAccount, RecommendationPlan
from trade_proposer_app.persistence.models import Base, BrokerOrderExecutionRecord
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import BrokerCapabilities, FakeBrokerAdapter
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class StaticAdapterFactory:
    def __init__(self) -> None:
        self.adapters: dict[str, FakeBrokerAdapter] = {}

    def add(self, broker_account_id: str, broker: str = "fake") -> None:
        self.adapters[broker_account_id] = FakeBrokerAdapter(
            capabilities=BrokerCapabilities(broker=broker, account_mode="paper")
        )

    def for_account_id(self, broker_account_id: str):
        return self.adapters[broker_account_id]


class MultiBrokerFanoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.factory = StaticAdapterFactory()
        self.settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)

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

    def _account(
        self, broker_account_id: str, *, autonomous: bool = True, halt: bool = False
    ) -> None:
        self.accounts.create(
            BrokerAccount(
                broker_account_id=broker_account_id,
                broker="alpaca",
                account_mode="paper",
                account_label=broker_account_id,
                enabled=True,
                autonomous_execution_enabled=autonomous,
                halt_enabled=halt,
                notional_cap_usd=1000.0,
            )
        )
        self.factory.add(broker_account_id, broker="alpaca")

    def test_one_plan_creates_one_candidate_per_enabled_broker_account(self) -> None:
        self._account("alpaca-paper-a")
        self._account("alpaca-paper-b")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.summary["broker_account_count"], 2)
        self.assertEqual(outcome.summary["submitted_order_count"], 2)
        self.assertEqual(
            {order.broker_account_id for order in outcome.orders},
            {"alpaca-paper-a", "alpaca-paper-b"},
        )
        self.assertEqual(self.session.query(BrokerOrderExecutionRecord).count(), 2)

    def test_account_halt_or_disabled_autonomy_skips_only_that_account(self) -> None:
        self._account("alpaca-paper-a")
        self._account("alpaca-paper-b", halt=True)
        self._account("alpaca-paper-c", autonomous=False)
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        by_account = {order.broker_account_id: order for order in outcome.orders}
        self.assertEqual(by_account["alpaca-paper-a"].status, "accepted")
        self.assertEqual(by_account["alpaca-paper-b"].status, "skipped")
        self.assertEqual(by_account["alpaca-paper-b"].error_message, "broker_account_halt_active")
        self.assertEqual(by_account["alpaca-paper-c"].status, "skipped")
        self.assertEqual(
            by_account["alpaca-paper-c"].error_message, "broker_account_autonomous_disabled"
        )

    def test_global_execution_disabled_skips_all_enabled_accounts(self) -> None:
        self.settings.set_order_execution_config(enabled=False, notional_per_plan=1000.0)
        self._account("alpaca-paper-a")
        self._account("alpaca-paper-b")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.summary["submitted_order_count"], 0)
        self.assertEqual(outcome.summary["skipped_order_count"], 2)
        self.assertEqual(
            {order.error_message for order in outcome.orders}, {"broker_execution_disabled"}
        )

    def test_global_halt_skips_all_enabled_accounts(self) -> None:
        self.settings.set_setting("broker_global_halt_enabled", "true")
        self._account("alpaca-paper-a")
        self._account("alpaca-paper-b")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.summary["submitted_order_count"], 0)
        self.assertEqual(outcome.summary["skipped_order_count"], 2)
        self.assertEqual(
            {order.error_message for order in outcome.orders}, {"broker_global_halt_active"}
        )

    def test_duplicate_run_plan_account_returns_existing_candidate_without_resubmit(self) -> None:
        self._account("alpaca-paper-a")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        first = service.execute_plans([self._plan()], run_id=1, job_id=2)
        second = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(first.orders[0].id, second.orders[0].id)
        self.assertEqual(second.summary["duplicate_order_count"], 1)
        self.assertEqual(len(self.factory.adapters["alpaca-paper-a"].orders), 1)


if __name__ == "__main__":
    unittest.main()
