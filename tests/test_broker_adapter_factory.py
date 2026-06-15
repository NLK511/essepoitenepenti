import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerAccount
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.brokers import (
    AlpacaPaperBrokerAdapter,
    EtoroDemoBrokerAdapter,
    EtoroLiveBrokerAdapter,
)
from trade_proposer_app.services.brokers.factory import BrokerAdapterFactory


class BrokerAdapterFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_factory_builds_alpaca_adapter_from_broker_account(self) -> None:
        accounts = BrokerAccountRepository(self.session)
        accounts.create(
            BrokerAccount(
                broker_account_id="alpaca-paper-main",
                broker="alpaca",
                account_mode="paper",
                account_label="paper",
            )
        )
        accounts.upsert_credentials(
            "alpaca-paper-main", {"api_key": "paper-key", "api_secret": "paper-secret"}
        )

        adapter = BrokerAdapterFactory(
            settings=SettingsRepository(self.session), accounts=accounts
        ).for_account_id("alpaca-paper-main")

        self.assertIsInstance(adapter, AlpacaPaperBrokerAdapter)
        self.assertEqual(adapter.get_capabilities().broker, "alpaca")

    def test_factory_builds_etoro_demo_adapter_for_demo_accounts(self) -> None:
        accounts = BrokerAccountRepository(self.session)
        accounts.create(
            BrokerAccount(
                broker_account_id="etoro-demo-main",
                broker="etoro",
                account_mode="demo",
                account_label="demo",
            )
        )
        accounts.upsert_credentials("etoro-demo-main", {"x_api_key": "api", "x_user_key": "user"})

        adapter = BrokerAdapterFactory(
            settings=SettingsRepository(self.session), accounts=accounts
        ).for_account_id("etoro-demo-main")

        self.assertIsInstance(adapter, EtoroDemoBrokerAdapter)

    def test_factory_builds_etoro_live_fail_closed_adapter_for_live_accounts(self) -> None:
        accounts = BrokerAccountRepository(self.session)
        accounts.create(
            BrokerAccount(
                broker_account_id="etoro-live-main",
                broker="etoro",
                account_mode="live",
                account_label="live",
            )
        )
        accounts.upsert_credentials("etoro-live-main", {"x_api_key": "api", "x_user_key": "user"})

        adapter = BrokerAdapterFactory(
            settings=SettingsRepository(self.session), accounts=accounts
        ).for_account_id("etoro-live-main")

        self.assertIsInstance(adapter, EtoroLiveBrokerAdapter)

    def test_factory_falls_back_to_legacy_alpaca_provider_credentials(self) -> None:
        settings = SettingsRepository(self.session)
        settings.upsert_provider_credential("alpaca", "paper-key", "paper-secret")

        adapter = BrokerAdapterFactory(settings=settings).for_legacy_config(
            {"broker": "alpaca", "account_mode": "paper"}
        )

        self.assertIsInstance(adapter, AlpacaPaperBrokerAdapter)


if __name__ == "__main__":
    unittest.main()
