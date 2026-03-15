from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.persistence.models import AppSettingRecord, ProviderCredentialRecord
from trade_proposer_app.security import credential_cipher

DEFAULT_PROVIDERS = ("openai", "anthropic", "newsapi", "finnhub", "alpha_vantage", "alpaca")
DEFAULT_SUMMARY_PROMPT = (
    "Create a very short financial news summary in 2-3 sentences. "
    "Focus on the main event or events driving this ticker's price fluctuation today. "
    "Explain how those events fit into the current industry context and the broader global macroeconomic stage. "
    "Be specific, factual, and concise. Return only the summary paragraph."
)
DEFAULT_APP_SETTINGS = {
    "confidence_threshold": "60",
    "optimization_minimum_resolved_trades": "50",
    "summary_backend": "news_digest",
    "summary_model": "",
    "summary_timeout_seconds": "60",
    "summary_max_tokens": "220",
    "summary_pi_command": "pi",
    "summary_pi_agent_dir": "",
    "summary_pi_cli_args": "",
    "summary_prompt": DEFAULT_SUMMARY_PROMPT,
}
SUMMARY_SETTING_KEYS = (
    "summary_backend",
    "summary_model",
    "summary_timeout_seconds",
    "summary_max_tokens",
    "summary_pi_command",
    "summary_pi_agent_dir",
    "summary_pi_cli_args",
    "summary_prompt",
)


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_settings(self) -> list[AppSetting]:
        setting_map = self.get_setting_map()
        return [AppSetting(key=k, value=v) for k, v in sorted(setting_map.items())]

    def set_setting(self, key: str, value: str) -> AppSetting:
        record = self.session.get(AppSettingRecord, key)
        if record is None:
            record = AppSettingRecord(key=key, value=value)
            self.session.add(record)
        else:
            record.value = value
        self.session.commit()
        return AppSetting(key=record.key, value=record.value)

    def set_settings(self, values: dict[str, str]) -> list[AppSetting]:
        saved: list[AppSetting] = []
        for key, value in values.items():
            saved.append(self.set_setting(key, value))
        return saved

    def get_setting_map(self) -> dict[str, str]:
        values = dict(DEFAULT_APP_SETTINGS)
        records = self.session.scalars(select(AppSettingRecord)).all()
        values.update({record.key: record.value for record in records})
        return values

    def get_summary_settings(self) -> dict[str, str]:
        setting_map = self.get_setting_map()
        return {key: setting_map.get(key, DEFAULT_APP_SETTINGS.get(key, "")) for key in SUMMARY_SETTING_KEYS}

    def get_optimization_minimum_resolved_trades(self) -> int:
        setting_map = self.get_setting_map()
        raw_value = setting_map.get(
            "optimization_minimum_resolved_trades",
            DEFAULT_APP_SETTINGS["optimization_minimum_resolved_trades"],
        )
        try:
            parsed = int((raw_value or "").strip())
        except (TypeError, ValueError):
            parsed = int(DEFAULT_APP_SETTINGS["optimization_minimum_resolved_trades"])
        return max(1, parsed)

    def list_provider_credentials(self) -> list[ProviderCredential]:
        existing = {
            row.provider: row
            for row in self.session.scalars(
                select(ProviderCredentialRecord).order_by(ProviderCredentialRecord.provider)
            ).all()
        }
        credentials: list[ProviderCredential] = []
        for provider in DEFAULT_PROVIDERS:
            row = existing.get(provider)
            credentials.append(
                ProviderCredential(
                    provider=provider,
                    api_key=credential_cipher.decrypt(row.api_key) if row else "",
                    api_secret=credential_cipher.decrypt(row.api_secret) if row else "",
                )
            )
        return credentials

    def get_provider_credential_map(self) -> dict[str, ProviderCredential]:
        return {item.provider: item for item in self.list_provider_credentials()}

    def upsert_provider_credential(self, provider: str, api_key: str, api_secret: str) -> ProviderCredential:
        encrypted_api_key = credential_cipher.encrypt(api_key)
        encrypted_api_secret = credential_cipher.encrypt(api_secret)
        record = self.session.get(ProviderCredentialRecord, provider)
        if record is None:
            record = ProviderCredentialRecord(
                provider=provider,
                api_key=encrypted_api_key,
                api_secret=encrypted_api_secret,
            )
            self.session.add(record)
        else:
            record.api_key = encrypted_api_key
            record.api_secret = encrypted_api_secret
        self.session.commit()
        return ProviderCredential(
            provider=record.provider,
            api_key=credential_cipher.decrypt(record.api_key),
            api_secret=credential_cipher.decrypt(record.api_secret),
        )
