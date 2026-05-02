from __future__ import annotations

from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import AppSetting
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.settings_domains import SettingsDomainService


class SettingsMutationService:
    def __init__(self, session: Session | None = None, repository: SettingsRepository | None = None) -> None:
        if repository is None:
            if session is None:
                raise ValueError("session or repository is required")
            repository = SettingsRepository(session)
        self.repository = repository

    def set_app_setting(self, *, key: str, value: str) -> AppSetting:
        return self.repository.set_setting(key=key.strip(), value=value.strip())

    def set_confidence_threshold(self, value: str) -> AppSetting:
        return self.repository.set_confidence_threshold(self._float(value, 60.0))

    def set_evaluation_realism_settings(
        self,
        *,
        stop_buffer_pct: str = "0.05",
        take_profit_buffer_pct: str = "0.05",
        friction_pct: str = "0.1",
    ) -> dict[str, float]:
        try:
            return self.repository.set_evaluation_realism_config(
                stop_buffer_pct=self._float(stop_buffer_pct, 0.05),
                take_profit_buffer_pct=self._float(take_profit_buffer_pct, 0.05),
                friction_pct=self._float(friction_pct, 0.1),
            )
        except ValueError as exc:
            raise ValueError(f"invalid evaluation realism settings: {exc}") from exc

    def set_summary_settings(
        self,
        *,
        backend: str,
        model: str = "",
        timeout_seconds: str = "60",
        max_tokens: str = "220",
        pi_command: str = "pi",
        pi_agent_dir: str = "",
        pi_cli_args: str = "",
        prompt: str = "",
    ) -> dict[str, object]:
        settings_map = self.repository.get_setting_map()
        self.repository.set_settings(
            {
                "summary_backend": backend.strip() or settings_map["summary_backend"],
                "summary_model": model.strip(),
                "summary_timeout_seconds": timeout_seconds.strip() or settings_map["summary_timeout_seconds"],
                "summary_max_tokens": max_tokens.strip() or settings_map["summary_max_tokens"],
                "summary_pi_command": pi_command.strip() or settings_map["summary_pi_command"],
                "summary_pi_agent_dir": pi_agent_dir.strip(),
                "summary_pi_cli_args": pi_cli_args.strip(),
                "summary_prompt": prompt.strip() or settings_map["summary_prompt"],
            }
        )
        return {"settings": SettingsDomainService(repository=self.repository).operator_settings().summary}

    def set_news_settings(
        self,
        *,
        macro_article_limit: str = "12",
        industry_article_limit: str = "12",
        ticker_article_limit: str = "12",
    ) -> dict[str, object]:
        settings_map = self.repository.get_setting_map()
        self.repository.set_settings(
            {
                "news_macro_article_limit": macro_article_limit.strip() or settings_map.get("news_macro_article_limit", "12"),
                "news_industry_article_limit": industry_article_limit.strip() or settings_map.get("news_industry_article_limit", "12"),
                "news_ticker_article_limit": ticker_article_limit.strip() or settings_map.get("news_ticker_article_limit", "12"),
            }
        )
        return {"status": "success"}

    def set_social_settings(
        self,
        *,
        sentiment_enabled: str = "false",
        nitter_enabled: str = "false",
        nitter_base_url: str = "http://127.0.0.1:8080",
        nitter_timeout_seconds: str = "6",
        nitter_max_items_per_query: str = "12",
        nitter_query_window_hours: str = "12",
        nitter_include_replies: str = "false",
        nitter_enable_ticker: str = "false",
        weight_news: str = "1.0",
        weight_social: str = "0.6",
        weight_macro: str = "0.2",
        weight_industry: str = "0.3",
        weight_ticker: str = "0.5",
        enable_author_weighting: str = "true",
        enable_engagement_weighting: str = "true",
        enable_duplicate_suppression: str = "true",
    ) -> dict[str, object]:
        self.repository.set_settings(
            {
                "social_sentiment_enabled": sentiment_enabled.strip().lower(),
                "social_nitter_enabled": nitter_enabled.strip().lower(),
                "social_nitter_base_url": nitter_base_url.strip() or "http://127.0.0.1:8080",
                "social_nitter_timeout_seconds": nitter_timeout_seconds.strip() or "6",
                "social_nitter_max_items_per_query": nitter_max_items_per_query.strip() or "12",
                "social_nitter_query_window_hours": nitter_query_window_hours.strip() or "12",
                "social_nitter_include_replies": nitter_include_replies.strip().lower(),
                "social_nitter_enable_ticker": nitter_enable_ticker.strip().lower(),
                "social_weight_news": weight_news.strip() or "1.0",
                "social_weight_social": weight_social.strip() or "0.6",
                "social_weight_macro": weight_macro.strip() or "0.2",
                "social_weight_industry": weight_industry.strip() or "0.3",
                "social_weight_ticker": weight_ticker.strip() or "0.5",
                "social_enable_author_weighting": enable_author_weighting.strip().lower(),
                "social_enable_engagement_weighting": enable_engagement_weighting.strip().lower(),
                "social_enable_duplicate_suppression": enable_duplicate_suppression.strip().lower(),
            }
        )
        return {"settings": SettingsDomainService(repository=self.repository).operator_settings().social}

    def set_signal_gating_tuning_settings(
        self,
        *,
        threshold_offset: str = "0",
        confidence_adjustment: str = "0",
        near_miss_gap_cutoff: str = "0",
        shortlist_aggressiveness: str = "0",
        degraded_penalty: str = "0",
    ) -> dict[str, object]:
        try:
            config = self.repository.set_signal_gating_tuning_config(
                threshold_offset=self._float(threshold_offset, 0.0),
                confidence_adjustment=self._float(confidence_adjustment, 0.0),
                near_miss_gap_cutoff=self._float(near_miss_gap_cutoff, 0.0),
                shortlist_aggressiveness=self._float(shortlist_aggressiveness, 0.0),
                degraded_penalty=self._float(degraded_penalty, 0.0),
            )
        except ValueError as exc:
            raise ValueError(f"invalid signal gating tuning settings: {exc}") from exc
        return {"signal_gating_tuning": config}

    def set_plan_generation_tuning_settings(
        self,
        *,
        auto_enabled: str = "false",
        auto_promote_enabled: str = "false",
        min_actionable_resolved: str = "20",
        min_validation_resolved: str = "8",
    ) -> dict[str, object]:
        try:
            config = self.repository.set_plan_generation_tuning_settings(
                auto_enabled=self._bool(auto_enabled),
                auto_promote_enabled=self._bool(auto_promote_enabled),
                min_actionable_resolved=self._int(min_actionable_resolved, 20),
                min_validation_resolved=self._int(min_validation_resolved, 8),
            )
        except ValueError as exc:
            raise ValueError(f"invalid plan generation tuning settings: {exc}") from exc
        return {"plan_generation_tuning": config}

    def set_plan_generation_active_config_version_id(self, config_version_id: int | None) -> AppSetting:
        return self.repository.set_plan_generation_active_config_version_id(config_version_id)

    def set_risk_management_settings(
        self,
        *,
        enabled: str = "true",
        max_daily_realized_loss_usd: str = "50",
        max_open_positions: str = "3",
        max_open_notional_usd: str = "3000",
        max_position_notional_usd: str = "1000",
        max_same_ticker_open_positions: str = "1",
        max_consecutive_losses: str = "3",
    ) -> dict[str, object]:
        try:
            config = self.repository.set_risk_management_config(
                enabled=self._bool(enabled),
                max_daily_realized_loss_usd=self._float(max_daily_realized_loss_usd, 50.0),
                max_open_positions=self._int(max_open_positions, 3),
                max_open_notional_usd=self._float(max_open_notional_usd, 3000.0),
                max_position_notional_usd=self._float(max_position_notional_usd, 1000.0),
                max_same_ticker_open_positions=self._int(max_same_ticker_open_positions, 1),
                max_consecutive_losses=self._int(max_consecutive_losses, 3),
            )
        except ValueError as exc:
            raise ValueError(f"invalid risk management settings: {exc}") from exc
        return {"risk_management": config}

    def set_order_execution_settings(
        self,
        *,
        enabled: str = "false",
        broker: str = "alpaca",
        account_mode: str = "paper",
        notional_per_plan: str = "1000",
    ) -> dict[str, object]:
        try:
            config = self.repository.set_order_execution_config(
                enabled=self._bool(enabled),
                broker=broker,
                account_mode=account_mode,
                notional_per_plan=self._float(notional_per_plan, 1000.0),
            )
        except ValueError as exc:
            raise ValueError(f"invalid order execution settings: {exc}") from exc
        return {"order_execution": config}

    def set_provider_credential(self, *, provider: str, api_key: str = "", api_secret: str = "") -> dict[str, str]:
        try:
            credential = self.repository.upsert_provider_credential(
                provider=provider.strip(),
                api_key=api_key.strip(),
                api_secret=api_secret.strip(),
            )
        except ValueError as exc:
            raise ValueError(f"invalid provider credential: {exc}") from exc
        return {"provider": credential.provider, "api_key": credential.api_key}

    def set_risk_halt(self, *, enabled: bool, reason: str = "") -> dict[str, object]:
        return self.repository.set_risk_halt(enabled=enabled, reason=reason.strip())

    @staticmethod
    def _bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _float(value: str, default: float) -> float:
        try:
            raw = (value or "").strip()
            return float(raw) if raw else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int(value: str, default: int) -> int:
        try:
            raw = (value or "").strip()
            return int(raw) if raw else default
        except (TypeError, ValueError):
            return default
