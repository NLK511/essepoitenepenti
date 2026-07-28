import unittest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import BrokerAccount, RecommendationPlan
from trade_proposer_app.persistence.models import Base, BrokerOrderExecutionRecord
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import (
    BrokerAdapterResultStatus,
    BrokerCapabilities,
    BrokerCredentialValidation,
    BrokerInstrument,
    BrokerOrderResult,
    FakeBrokerAdapter,
)
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


class CapturingEtoroDemoAdapter(FakeBrokerAdapter):
    def __init__(self, *, instrument: BrokerInstrument | None = None) -> None:
        super().__init__(
            capabilities=BrokerCapabilities(
                broker="etoro",
                account_mode="demo",
                supported_actions=["long"],
                supported_order_types=["market"],
            )
        )
        self.instrument = instrument or BrokerInstrument(
            symbol="AAPL",
            instrument_id="123",
            tradable=True,
            ambiguous=False,
            product_type="stock",
            currency="usd",
        )
        self.submitted_requests = []

    def validate_credentials(self) -> BrokerCredentialValidation:
        return BrokerCredentialValidation(
            valid=True,
            permission_scope="demo",
            account_mode="demo",
            permissions=["demo_trading"],
        )

    def resolve_instrument(self, symbol: str) -> BrokerInstrument:
        return self.instrument

    def submit_order(self, request):
        self.submitted_requests.append(request)
        return BrokerOrderResult(
            status=BrokerAdapterResultStatus.SUCCESS,
            operation="submit_order",
            client_request_id=request.client_order_id,
            broker_order_id="etoro-order-1",
            broker_status="accepted",
            payload={"orderId": "etoro-order-1"},
        )


class MultiBrokerFanoutTests(unittest.TestCase):
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
            computed_at=datetime.now(UTC),
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

    def test_multi_broker_candidates_use_normalized_broker_agnostic_price_levels(self) -> None:
        self._account("alpaca-paper-a")
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )
        plan = self._plan()
        plan.entry_price_low = 597.292
        plan.entry_price_high = 597.292
        plan.stop_loss = 578.1666
        plan.take_profit = 630.1101

        outcome = service.execute_plans([plan], run_id=1, job_id=2)

        order = outcome.orders[0]
        self.assertEqual(order.entry_price, 597.29)
        self.assertEqual(order.stop_loss, 578.17)
        self.assertEqual(order.take_profit, 630.11)
        self.assertEqual(order.request_payload["limit_price"], 597.29)
        self.assertEqual(order.request_payload["stop_loss"], {"stop_price": 578.17})
        self.assertEqual(order.request_payload["take_profit"], {"limit_price": 630.11})

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
        self.settings.set_order_execution_config(enabled=False, broker="alpaca", account_mode="paper", notional_per_plan=1000.0)
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

    def test_etoro_demo_candidate_resolves_instrument_and_uses_market_amount_request(self) -> None:
        account_id = "etoro-demo-main"
        self.accounts.create(
            BrokerAccount(
                broker_account_id=account_id,
                broker="etoro",
                account_mode="demo",
                account_label=account_id,
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=250.0,
            )
        )
        adapter = CapturingEtoroDemoAdapter()
        self.factory.adapters[account_id] = adapter
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        order = outcome.orders[0]
        self.assertEqual(order.status, "accepted")
        self.assertEqual(order.broker_order_id, "etoro-order-1")
        self.assertEqual(order.order_type, "market")
        self.assertEqual(order.request_payload["instrumentId"], "123")
        submitted = adapter.submitted_requests[0]
        self.assertEqual(submitted.order_type, "market")
        self.assertEqual(submitted.instrument_id, "123")
        self.assertEqual(submitted.notional_amount, 250.0)

    def test_etoro_demo_amount_sizing_allows_sub_one_share_notional(self) -> None:
        account_id = "etoro-demo-main"
        self.accounts.create(
            BrokerAccount(
                broker_account_id=account_id,
                broker="etoro",
                account_mode="demo",
                account_label=account_id,
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=25.0,
            )
        )
        adapter = CapturingEtoroDemoAdapter()
        self.factory.adapters[account_id] = adapter
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        order = outcome.orders[0]
        self.assertEqual(order.status, "accepted")
        self.assertEqual(order.quantity, 0)
        self.assertEqual(order.notional_amount, 25.0)
        self.assertEqual(adapter.submitted_requests[0].notional_amount, 25.0)

    def test_etoro_demo_ambiguous_instrument_is_auditable_skip(self) -> None:
        account_id = "etoro-demo-main"
        self.accounts.create(
            BrokerAccount(
                broker_account_id=account_id,
                broker="etoro",
                account_mode="demo",
                account_label=account_id,
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=250.0,
            )
        )
        self.factory.adapters[account_id] = CapturingEtoroDemoAdapter(
            instrument=BrokerInstrument(
                symbol="AAPL",
                instrument_id="",
                tradable=False,
                ambiguous=True,
                product_type="unknown",
            )
        )
        service = MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=self.factory,
        )

        outcome = service.execute_plans([self._plan()], run_id=1, job_id=2)

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "etoro_instrument_ambiguous")


if __name__ == "__main__":
    unittest.main()
