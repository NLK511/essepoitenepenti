import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerAccount, BrokerOrderExecution
from trade_proposer_app.persistence.models import Base, BrokerOrderExecutionRecord
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.default_jobs import ensure_default_broker_accounts


class BrokerAccountRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_bootstrap_default_etoro_demo_account_is_disabled_and_capped(self) -> None:
        repo = BrokerAccountRepository(self.session)

        account = repo.ensure_default_etoro_demo_account()

        self.assertEqual(account.broker_account_id, "etoro-demo-main")
        self.assertEqual(account.broker, "etoro")
        self.assertEqual(account.account_mode, "demo")
        self.assertEqual(account.account_label, "eToro Demo")
        self.assertFalse(account.enabled)
        self.assertFalse(account.autonomous_execution_enabled)
        self.assertTrue(account.manual_actions_enabled)
        self.assertEqual(account.symbol_allowlist, [])
        self.assertEqual(account.supported_actions, ["long"])
        self.assertEqual(account.supported_instruments, ["resolved_equity"])
        self.assertEqual(account.supported_order_types, ["market"])
        self.assertEqual(account.notional_cap_usd, 25.0)
        self.assertEqual(account.max_open_positions, 1)
        self.assertTrue(account.risk_settings["demo_only"])
        self.assertTrue(account.risk_settings["side_by_side_trial_required"])

    def test_startup_bootstrap_ensures_default_etoro_demo_account_idempotently(self) -> None:
        first = ensure_default_broker_accounts(self.session)
        second = ensure_default_broker_accounts(self.session)

        self.assertEqual(first["default_etoro_demo_account_id"], "etoro-demo-main")
        self.assertEqual(second["default_etoro_demo_account_id"], "etoro-demo-main")
        accounts = BrokerAccountRepository(self.session).list_all()
        self.assertEqual(
            [account.broker_account_id for account in accounts],
            ["etoro-demo-main"],
        )
        by_id = {account.broker_account_id: account for account in accounts}
        self.assertFalse(by_id["etoro-demo-main"].enabled)
        self.assertFalse(by_id["etoro-demo-main"].autonomous_execution_enabled)

    def test_account_label_is_mutable_but_account_id_is_stable(self) -> None:
        repo = BrokerAccountRepository(self.session)
        account = repo.create(
            BrokerAccount(
                broker_account_id="etoro-live-main",
                broker="etoro",
                account_mode="live",
                account_label="Main live",
            )
        )

        updated = repo.update_label(account.broker_account_id, "Renamed live")

        self.assertEqual(updated.broker_account_id, "etoro-live-main")
        self.assertEqual(updated.account_label, "Renamed live")
        self.assertEqual(repo.get("etoro-live-main").broker_account_id, account.broker_account_id)

    def test_credentials_are_scoped_to_broker_account_id(self) -> None:
        repo = BrokerAccountRepository(self.session)
        repo.create(
            BrokerAccount(
                broker_account_id="etoro-demo-a",
                broker="etoro",
                account_mode="demo",
                account_label="demo a",
            )
        )
        repo.create(
            BrokerAccount(
                broker_account_id="etoro-demo-b",
                broker="etoro",
                account_mode="demo",
                account_label="demo b",
            )
        )

        repo.upsert_credentials("etoro-demo-a", {"x_api_key": "api-a", "x_user_key": "user-a"})
        repo.upsert_credentials("etoro-demo-b", {"x_api_key": "api-b", "x_user_key": "user-b"})

        self.assertEqual(repo.get_credentials("etoro-demo-a")["x_user_key"], "user-a")
        self.assertEqual(repo.get_credentials("etoro-demo-b")["x_user_key"], "user-b")
        redacted = repo.list_accounts_redacted()
        self.assertEqual(redacted[0].credential_reference, "broker_account:etoro-demo-a")
        self.assertNotIn("user-a", str(redacted))

    def test_enabled_accounts_excludes_disabled_accounts(self) -> None:
        repo = BrokerAccountRepository(self.session)
        repo.create(
            BrokerAccount(
                broker_account_id="alpaca-paper-enabled",
                broker="alpaca",
                account_mode="paper",
                account_label="enabled",
                enabled=True,
            )
        )
        repo.create(
            BrokerAccount(
                broker_account_id="etoro-demo-disabled",
                broker="etoro",
                account_mode="demo",
                account_label="disabled",
                enabled=False,
            )
        )

        enabled_ids = [account.broker_account_id for account in repo.list_enabled()]

        self.assertEqual(enabled_ids, ["alpaca-paper-enabled"])

    def test_order_candidate_uniqueness_is_scoped_by_run_plan_and_broker_account(self) -> None:
        orders = BrokerOrderExecutionRepository(self.session)
        first = BrokerOrderExecution(
            broker_account_id="alpaca-paper-default",
            broker="alpaca",
            account_mode="paper",
            recommendation_plan_id=123,
            run_id=456,
            ticker="AAPL",
            action="long",
            side="buy",
            order_type="limit",
            client_order_id="alpaca-1",
        )
        created = orders.create_candidate_once(first)
        duplicate = orders.create_candidate_once(
            first.model_copy(update={"client_order_id": "alpaca-2"})
        )

        self.assertEqual(duplicate.id, created.id)
        orders.create_candidate_once(
            first.model_copy(
                update={
                    "broker_account_id": "etoro-demo-main",
                    "broker": "etoro",
                    "client_order_id": "etoro-1",
                }
            )
        )
        self.assertEqual(self.session.query(BrokerOrderExecutionRecord).count(), 2)

    def test_global_live_caps_round_trip(self) -> None:
        settings = SettingsRepository(self.session)

        saved = settings.set_global_broker_risk_caps(
            max_live_open_notional_usd=250.0,
            max_live_daily_drawdown_usd=25.0,
            max_live_daily_drawdown_pct=5.0,
            max_live_order_count_per_day=3,
        )

        self.assertEqual(saved["global_max_live_open_notional_usd"], 250.0)
        self.assertEqual(
            settings.get_global_broker_risk_caps()["global_max_live_order_count_per_day"], 3
        )


if __name__ == "__main__":
    unittest.main()
