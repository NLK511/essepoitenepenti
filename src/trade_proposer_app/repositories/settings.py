from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.persistence.models import AppSettingRecord, ProviderCredentialRecord
from trade_proposer_app.security import credential_cipher
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config

DEFAULT_PROVIDERS = ("openai", "anthropic", "newsapi", "finnhub", "alpha_vantage", "alpaca")
DEFAULT_SUMMARY_PROMPT = (
    "Create a very short financial news summary in 2-3 sentences. "
    "Focus on the main event or events driving this ticker's price fluctuation today. "
    "Explain how those events fit into the current industry context and the broader global macroeconomic stage. "
    "Be specific, factual, and concise. Return only the summary paragraph."
)
DEFAULT_APP_SETTINGS = {
    "confidence_threshold": "60",
    "signal_gating_tuning_threshold_offset": "0",
    "signal_gating_tuning_confidence_adjustment": "0",
    "signal_gating_tuning_near_miss_gap_cutoff": "0",
    "signal_gating_tuning_shortlist_aggressiveness": "0",
    "signal_gating_tuning_degraded_penalty": "0",
    "plan_generation_active_config_version_id": "",
    "plan_generation_tuning_auto_enabled": "false",
    "plan_generation_tuning_auto_promote_enabled": "false",
    "plan_generation_tuning_min_actionable_resolved": "20",
    "plan_generation_tuning_min_validation_resolved": "8",
    "order_execution_enabled": "false",
    "order_execution_broker": "alpaca",
    "order_execution_account_mode": "paper",
    "order_execution_notional_per_plan": "1000",
    "summary_backend": "pi_agent",
    "summary_model": "",
    "summary_timeout_seconds": "60",
    "summary_max_tokens": "220",
    "summary_pi_command": "pi",
    "summary_pi_agent_dir": "",
    "summary_pi_cli_args": "",
    "summary_prompt": DEFAULT_SUMMARY_PROMPT,
    "social_sentiment_enabled": "false",
    "social_nitter_enabled": "false",
    "social_nitter_base_url": "http://127.0.0.1:8080",
    "social_nitter_timeout_seconds": "6",
    "social_nitter_max_items_per_query": "12",
    "social_nitter_query_window_hours": "12",
    "social_nitter_include_replies": "false",
    "social_nitter_enable_ticker": "false",
    "social_weight_news": "1.0",
    "social_weight_social": "0.6",
    "social_weight_macro": "0.2",
    "social_weight_industry": "0.3",
    "social_weight_ticker": "0.5",
    "social_enable_author_weighting": "true",
    "social_enable_engagement_weighting": "true",
    "social_enable_duplicate_suppression": "true",
    "evaluation_realism_stop_buffer_pct": "0.05",
    "evaluation_realism_take_profit_buffer_pct": "0.05",
    "evaluation_realism_friction_pct": "0.1",
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
SOCIAL_SETTING_KEYS = (
    "social_sentiment_enabled",
    "social_nitter_enabled",
    "social_nitter_base_url",
    "social_nitter_timeout_seconds",
    "social_nitter_max_items_per_query",
    "social_nitter_query_window_hours",
    "social_nitter_include_replies",
    "social_nitter_enable_ticker",
    "social_weight_news",
    "social_weight_social",
    "social_weight_macro",
    "social_weight_industry",
    "social_weight_ticker",
    "social_enable_author_weighting",
    "social_enable_engagement_weighting",
    "social_enable_duplicate_suppression",
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

    def get_social_settings(self) -> dict[str, str]:
        setting_map = self.get_setting_map()
        return {key: setting_map.get(key, DEFAULT_APP_SETTINGS.get(key, "")) for key in SOCIAL_SETTING_KEYS}

    def get_evaluation_realism_config(self) -> dict[str, float]:
        setting_map = self.get_setting_map()
        return {
            "stop_buffer_pct": self._get_float(setting_map, "evaluation_realism_stop_buffer_pct", 0.05),
            "take_profit_buffer_pct": self._get_float(setting_map, "evaluation_realism_take_profit_buffer_pct", 0.05),
            "friction_pct": self._get_float(setting_map, "evaluation_realism_friction_pct", 0.1),
        }

    def set_evaluation_realism_config(self, *, stop_buffer_pct: float, take_profit_buffer_pct: float, friction_pct: float) -> dict[str, float]:
        self.set_settings(
            {
                "evaluation_realism_stop_buffer_pct": f"{float(stop_buffer_pct):.4f}".rstrip("0").rstrip("."),
                "evaluation_realism_take_profit_buffer_pct": f"{float(take_profit_buffer_pct):.4f}".rstrip("0").rstrip("."),
                "evaluation_realism_friction_pct": f"{float(friction_pct):.4f}".rstrip("0").rstrip("."),
            }
        )
        return self.get_evaluation_realism_config()

    def get_confidence_threshold(self) -> float:
        setting_map = self.get_setting_map()
        raw_value = setting_map.get("confidence_threshold", DEFAULT_APP_SETTINGS["confidence_threshold"])
        try:
            parsed = float((raw_value or "").strip())
        except (TypeError, ValueError):
            parsed = float(DEFAULT_APP_SETTINGS["confidence_threshold"])
        return max(0.0, parsed)

    def set_confidence_threshold(self, value: float) -> AppSetting:
        normalized = f"{float(value):.2f}".rstrip("0").rstrip(".")
        return self.set_setting("confidence_threshold", normalized)

    def get_signal_gating_tuning_config(self) -> dict[str, float]:
        setting_map = self.get_setting_map()
        return {
            "threshold_offset": self._get_float(setting_map, "signal_gating_tuning_threshold_offset", 0.0),
            "confidence_adjustment": self._get_float(setting_map, "signal_gating_tuning_confidence_adjustment", 0.0),
            "near_miss_gap_cutoff": self._get_float(setting_map, "signal_gating_tuning_near_miss_gap_cutoff", 0.0),
            "shortlist_aggressiveness": self._get_float(setting_map, "signal_gating_tuning_shortlist_aggressiveness", 0.0),
            "degraded_penalty": self._get_float(setting_map, "signal_gating_tuning_degraded_penalty", 0.0),
        }

    def set_signal_gating_tuning_config(self, *, threshold_offset: float, confidence_adjustment: float, near_miss_gap_cutoff: float, shortlist_aggressiveness: float, degraded_penalty: float) -> dict[str, float]:
        self.set_settings(
            {
                "signal_gating_tuning_threshold_offset": f"{float(threshold_offset):.2f}".rstrip("0").rstrip("."),
                "signal_gating_tuning_confidence_adjustment": f"{float(confidence_adjustment):.2f}".rstrip("0").rstrip("."),
                "signal_gating_tuning_near_miss_gap_cutoff": f"{float(near_miss_gap_cutoff):.2f}".rstrip("0").rstrip("."),
                "signal_gating_tuning_shortlist_aggressiveness": f"{float(shortlist_aggressiveness):.2f}".rstrip("0").rstrip("."),
                "signal_gating_tuning_degraded_penalty": f"{float(degraded_penalty):.2f}".rstrip("0").rstrip("."),
            }
        )
        return self.get_signal_gating_tuning_config()

    def get_plan_generation_active_config_version_id(self) -> int | None:
        setting_map = self.get_setting_map()
        raw_value = (setting_map.get("plan_generation_active_config_version_id", "") or "").strip()
        if not raw_value:
            return None
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def set_plan_generation_active_config_version_id(self, config_version_id: int | None) -> AppSetting:
        return self.set_setting("plan_generation_active_config_version_id", "" if config_version_id is None else str(int(config_version_id)))

    def get_plan_generation_tuning_settings(self) -> dict[str, object]:
        setting_map = self.get_setting_map()
        return {
            "active_config_version_id": self.get_plan_generation_active_config_version_id(),
            "auto_enabled": self._get_bool(setting_map, "plan_generation_tuning_auto_enabled", False),
            "auto_promote_enabled": self._get_bool(setting_map, "plan_generation_tuning_auto_promote_enabled", False),
            "min_actionable_resolved": self._get_int(setting_map, "plan_generation_tuning_min_actionable_resolved", 20),
            "min_validation_resolved": self._get_int(setting_map, "plan_generation_tuning_min_validation_resolved", 8),
        }

    def set_plan_generation_tuning_settings(self, *, auto_enabled: bool, auto_promote_enabled: bool, min_actionable_resolved: int, min_validation_resolved: int) -> dict[str, object]:
        self.set_settings(
            {
                "plan_generation_tuning_auto_enabled": str(bool(auto_enabled)).lower(),
                "plan_generation_tuning_auto_promote_enabled": str(bool(auto_promote_enabled)).lower(),
                "plan_generation_tuning_min_actionable_resolved": str(max(1, int(min_actionable_resolved))),
                "plan_generation_tuning_min_validation_resolved": str(max(1, int(min_validation_resolved))),
            }
        )
        return self.get_plan_generation_tuning_settings()

    def get_plan_generation_active_config(self, configs_repository) -> dict[str, float]:
        config_version_id = self.get_plan_generation_active_config_version_id()
        if config_version_id is None:
            return normalize_plan_generation_tuning_config(None)
        try:
            version = configs_repository.get_config_version(config_version_id)
        except ValueError:
            return normalize_plan_generation_tuning_config(None)
        return normalize_plan_generation_tuning_config(version.config)

    def get_order_execution_config(self) -> dict[str, object]:
        setting_map = self.get_setting_map()
        return {
            "enabled": self._get_bool(setting_map, "order_execution_enabled", False),
            "broker": (setting_map.get("order_execution_broker", "alpaca") or "alpaca").strip().lower(),
            "account_mode": (setting_map.get("order_execution_account_mode", "paper") or "paper").strip().lower(),
            "notional_per_plan": self._get_float(setting_map, "order_execution_notional_per_plan", 1000.0),
        }

    def set_order_execution_config(self, *, enabled: bool, broker: str = "alpaca", account_mode: str = "paper", notional_per_plan: float = 1000.0) -> dict[str, object]:
        self.set_settings(
            {
                "order_execution_enabled": str(bool(enabled)).lower(),
                "order_execution_broker": broker.strip().lower() or "alpaca",
                "order_execution_account_mode": account_mode.strip().lower() or "paper",
                "order_execution_notional_per_plan": f"{float(notional_per_plan):.4f}".rstrip("0").rstrip("."),
            }
        )
        return self.get_order_execution_config()

    @staticmethod
    def _get_float(setting_map: dict[str, str], key: str, default: float) -> float:
        raw_value = setting_map.get(key, str(default))
        try:
            return float((raw_value or "").strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_int(setting_map: dict[str, str], key: str, default: int) -> int:
        raw_value = setting_map.get(key, str(default))
        try:
            return int((raw_value or "").strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_bool(setting_map: dict[str, str], key: str, default: bool) -> bool:
        raw_value = (setting_map.get(key, str(default)) or "").strip().lower()
        if raw_value in {"1", "true", "yes", "on"}:
            return True
        if raw_value in {"0", "false", "no", "off"}:
            return False
        return default

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

    def list_provider_credentials_redacted(self) -> list[ProviderCredential]:
        return [ProviderCredential(provider=item.provider, api_key=item.api_key, api_secret="") for item in self.list_provider_credentials()]

    def get_provider_credential_map(self) -> dict[str, ProviderCredential]:
        return {item.provider: item for item in self.list_provider_credentials()}

    def upsert_provider_credential(self, provider: str, api_key: str, api_secret: str) -> ProviderCredential:
        api_key = api_key.strip()
        api_secret = api_secret.strip()
        record = self.session.get(ProviderCredentialRecord, provider)
        if record is None:
            if not api_key or not api_secret:
                raise ValueError("api key and api secret are required when creating a provider credential")
            record = ProviderCredentialRecord(
                provider=provider,
                api_key=credential_cipher.encrypt(api_key),
                api_secret=credential_cipher.encrypt(api_secret),
            )
            self.session.add(record)
        else:
            if api_key:
                record.api_key = credential_cipher.encrypt(api_key)
            if api_secret:
                record.api_secret = credential_cipher.encrypt(api_secret)
        self.session.commit()
        return ProviderCredential(
            provider=record.provider,
            api_key=credential_cipher.decrypt(record.api_key),
            api_secret=credential_cipher.decrypt(record.api_secret),
        )
