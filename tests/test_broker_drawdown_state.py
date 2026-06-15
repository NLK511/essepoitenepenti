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
from trade_proposer_app.services.brokers import FakeBrokerAdapter
from trade_proposer_app.services.multi_broker_execution import MultiBrokerExecutionService


class StaticAdapterFactory:
    def for_account_id(self, broker_account_id: str):
        return FakeBrokerAdapter()


class BrokerDrawdownStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.settings = SettingsRepository(self.session)
        self.accounts = BrokerAccountRepository(self.session)
        self.executions = BrokerOrderExecutionRepository(self.session)
        self.safety = BrokerAccountSafetyRepository(self.session)
        self.settings.set_order_execution_config(enabled=True, notional_per_plan=1000.0)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _account(self, **risk_settings: object) -> None:
        self.accounts.create(
            BrokerAccount(
                broker_account_id="etoro-live-main",
                broker="etoro",
                account_mode="live",
                account_label="live",
                enabled=True,
                autonomous_execution_enabled=True,
                notional_cap_usd=1000.0,
                risk_settings=risk_settings,
            )
        )

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

    def _execute(self):
        return MultiBrokerExecutionService(
            settings=self.settings,
            accounts=self.accounts,
            executions=self.executions,
            adapter_factory=StaticAdapterFactory(),
            safety=self.safety,
        ).execute_plans([self._plan()], run_id=1, job_id=2)

    def test_high_water_marks_persist_across_repository_instances(self) -> None:
        self._account()
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=950.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1100.0,
            broker_timezone="Europe/Rome",
            trusted=True,
            baseline_source="test",
        )

        reloaded = BrokerAccountSafetyRepository(self.session).get_drawdown_state("etoro-live-main")

        self.assertEqual(reloaded.current_equity, 950.0)
        self.assertEqual(reloaded.daily_high_water_equity, 1000.0)
        self.assertEqual(reloaded.total_high_water_equity, 1100.0)
        self.assertEqual(reloaded.broker_timezone, "Europe/Rome")
        self.assertTrue(reloaded.daily_boundary)

    def test_daily_drawdown_pct_blocks(self) -> None:
        self._account(max_daily_drawdown_pct=5)
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=940.0,
            daily_high_water_equity=1000.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

        outcome = self._execute()

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_daily_drawdown_limit_exceeded")

    def test_total_drawdown_pct_blocks(self) -> None:
        self._account(max_total_drawdown_pct=10)
        self.safety.record_drawdown_baseline(
            "etoro-live-main",
            current_equity=850.0,
            daily_high_water_equity=900.0,
            total_high_water_equity=1000.0,
            broker_timezone="UTC",
            trusted=True,
        )

        outcome = self._execute()

        self.assertEqual(outcome.orders[0].status, "skipped")
        self.assertEqual(outcome.orders[0].error_message, "risk_total_drawdown_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
