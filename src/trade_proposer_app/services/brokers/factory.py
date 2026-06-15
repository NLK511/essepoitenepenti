from __future__ import annotations

from collections.abc import Callable

from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClient
from trade_proposer_app.services.brokers.adapter import BrokerAdapter
from trade_proposer_app.services.brokers.alpaca import AlpacaPaperBrokerAdapter
from trade_proposer_app.services.brokers.etoro import (
    EtoroClient,
    EtoroDemoBrokerAdapter,
    EtoroLiveBrokerAdapter,
    EtoroReadOnlyBrokerAdapter,
)


class BrokerAdapterFactory:
    def __init__(
        self,
        *,
        settings: SettingsRepository,
        accounts: BrokerAccountRepository | None = None,
        alpaca_client_cls: Callable[..., AlpacaPaperClient] = AlpacaPaperClient,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.alpaca_client_cls = alpaca_client_cls

    def for_account_id(self, broker_account_id: str) -> BrokerAdapter:
        if self.accounts is None:
            raise ValueError("broker account repository is required for account-scoped adapters")
        account = self.accounts.get(broker_account_id)
        credentials = self.accounts.get_credentials(broker_account_id)
        return self._build(
            broker=account.broker,
            account_mode=account.account_mode,
            credentials=credentials,
            broker_account_id=broker_account_id,
        )

    def for_legacy_config(self, config: dict[str, object]) -> BrokerAdapter:
        broker = str(config.get("broker") or "alpaca").strip().lower()
        account_mode = str(config.get("account_mode") or "paper").strip().lower()
        credentials = {}
        if broker == "alpaca":
            credential = self.settings.get_provider_credential_map().get("alpaca")
            if credential is not None:
                credentials = {"api_key": credential.api_key, "api_secret": credential.api_secret}
        return self._build(
            broker=broker,
            account_mode=account_mode,
            credentials=credentials,
            broker_account_id=None,
        )

    def _build(
        self,
        *,
        broker: str,
        account_mode: str,
        credentials: dict[str, str],
        broker_account_id: str | None,
    ) -> BrokerAdapter:
        normalized_broker = broker.strip().lower()
        normalized_mode = account_mode.strip().lower()
        if normalized_broker == "alpaca" and normalized_mode == "paper":
            api_key = credentials.get("api_key") or credentials.get("APCA-API-KEY-ID") or ""
            api_secret = (
                credentials.get("api_secret") or credentials.get("APCA-API-SECRET-KEY") or ""
            )
            return AlpacaPaperBrokerAdapter(
                client=self.alpaca_client_cls(api_key=api_key, api_secret=api_secret)
            )
        if normalized_broker == "etoro":
            api_key = credentials.get("x_api_key") or credentials.get("api_key") or ""
            user_key = credentials.get("x_user_key") or credentials.get("user_key") or ""
            client = EtoroClient(api_key=api_key, user_key=user_key)
            if normalized_mode == "demo":
                return EtoroDemoBrokerAdapter(client=client)
            if normalized_mode == "live":
                return EtoroLiveBrokerAdapter(client=client)
            return EtoroReadOnlyBrokerAdapter(client=client)
        label = broker_account_id or f"{normalized_broker}:{normalized_mode}"
        raise NotImplementedError(f"broker adapter is not implemented for {label}")
