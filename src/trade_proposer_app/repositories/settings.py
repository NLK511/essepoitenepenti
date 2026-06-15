from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import AppSetting, ProviderCredential
from trade_proposer_app.persistence.models import AppSettingRecord, ProviderCredentialRecord
from trade_proposer_app.security import credential_cipher
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)

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
    "broker_global_halt_enabled": "false",
    "broker_global_halt_reason": "",
    "risk_management_enabled": "true",
    "risk_halt_enabled": "false",
    "risk_halt_reason": "",
    "risk_max_daily_realized_loss_usd": "50",
    "risk_max_open_positions": "3",
    "risk_max_open_notional_usd": "3000",
    "risk_max_position_notional_usd": "1000",
    "risk_max_same_ticker_open_positions": "1",
    "risk_max_consecutive_losses": "3",
    "global_max_live_open_notional_usd": "",
    "global_max_live_daily_drawdown_usd": "",
    "global_max_live_daily_drawdown_pct": "",
    "global_max_live_order_count_per_day": "",
    "steering_enabled": "false",
    "steering_dry_run": "true",
    "steering_cancel_expired_pending_orders_enabled": "true",
    "steering_cancel_invalidated_pending_orders_enabled": "true",
    "steering_move_to_profit_enabled": "true",
    "steering_close_on_severe_invalidation_enabled": "true",
    "steering_tighten_on_deterioration_enabled": "true",
    "steering_lower_tp_on_weakness_enabled": "true",
    "steering_pending_expiration_grace_minutes": "5",
    "steering_pending_min_confidence_percent": "55",
    "steering_pending_invalidation_required_signals": "2",
    "steering_pending_price_chase_limit_percent": "1.0",
    "steering_breakeven_trigger_percent": "0.75",
    "steering_min_profit_lock_percent": "0.10",
    "steering_position_close_confidence_percent": "40",
    "steering_position_close_required_signals": "3",
    "steering_position_min_hold_confidence_percent": "50",
    "steering_position_deterioration_required_signals": "2",
    "steering_deterioration_stop_cushion_percent": "0.35",
    "steering_weakened_thesis_tp_cushion_percent": "0.50",
    "steering_min_tp_distance_percent": "0.10",
    "steering_max_reconciliation_age_minutes": "30",
    "steering_min_reviewed_dry_run_decisions_before_enable": "30",
    "steering_min_reviewed_dry_run_amendments_before_enable": "10",
    "steering_min_reviewed_dry_run_close_now_before_enable": "10",
    "summary_backend": "pi_agent",
    "summary_model": "",
    "summary_timeout_seconds": "600",
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
        return {
            key: setting_map.get(key, DEFAULT_APP_SETTINGS.get(key, ""))
            for key in SUMMARY_SETTING_KEYS
        }

    def get_social_settings(self) -> dict[str, str]:
        setting_map = self.get_setting_map()
        return {
            key: setting_map.get(key, DEFAULT_APP_SETTINGS.get(key, ""))
            for key in SOCIAL_SETTING_KEYS
        }

    def get_evaluation_realism_config(self) -> dict[str, float]:
        setting_map = self.get_setting_map()
        return {
            "stop_buffer_pct": self._get_float(
                setting_map, "evaluation_realism_stop_buffer_pct", 0.05
            ),
            "take_profit_buffer_pct": self._get_float(
                setting_map, "evaluation_realism_take_profit_buffer_pct", 0.05
            ),
            "friction_pct": self._get_float(setting_map, "evaluation_realism_friction_pct", 0.1),
        }

    def set_evaluation_realism_config(
        self, *, stop_buffer_pct: float, take_profit_buffer_pct: float, friction_pct: float
    ) -> dict[str, float]:
        self.set_settings(
            {
                "evaluation_realism_stop_buffer_pct": f"{float(stop_buffer_pct):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "evaluation_realism_take_profit_buffer_pct": f"{float(take_profit_buffer_pct):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "evaluation_realism_friction_pct": f"{float(friction_pct):.4f}".rstrip("0").rstrip(
                    "."
                ),
            }
        )
        return self.get_evaluation_realism_config()

    def get_confidence_threshold(self) -> float:
        setting_map = self.get_setting_map()
        raw_value = setting_map.get(
            "confidence_threshold", DEFAULT_APP_SETTINGS["confidence_threshold"]
        )
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
            "threshold_offset": self._get_float(
                setting_map, "signal_gating_tuning_threshold_offset", 0.0
            ),
            "confidence_adjustment": self._get_float(
                setting_map, "signal_gating_tuning_confidence_adjustment", 0.0
            ),
            "near_miss_gap_cutoff": self._get_float(
                setting_map, "signal_gating_tuning_near_miss_gap_cutoff", 0.0
            ),
            "shortlist_aggressiveness": self._get_float(
                setting_map, "signal_gating_tuning_shortlist_aggressiveness", 0.0
            ),
            "degraded_penalty": self._get_float(
                setting_map, "signal_gating_tuning_degraded_penalty", 0.0
            ),
        }

    def set_signal_gating_tuning_config(
        self,
        *,
        threshold_offset: float,
        confidence_adjustment: float,
        near_miss_gap_cutoff: float,
        shortlist_aggressiveness: float,
        degraded_penalty: float,
    ) -> dict[str, float]:
        self.set_settings(
            {
                "signal_gating_tuning_threshold_offset": f"{float(threshold_offset):.2f}".rstrip(
                    "0"
                ).rstrip("."),
                "signal_gating_tuning_confidence_adjustment": f"{float(confidence_adjustment):.2f}".rstrip(
                    "0"
                ).rstrip("."),
                "signal_gating_tuning_near_miss_gap_cutoff": f"{float(near_miss_gap_cutoff):.2f}".rstrip(
                    "0"
                ).rstrip("."),
                "signal_gating_tuning_shortlist_aggressiveness": f"{float(shortlist_aggressiveness):.2f}".rstrip(
                    "0"
                ).rstrip("."),
                "signal_gating_tuning_degraded_penalty": f"{float(degraded_penalty):.2f}".rstrip(
                    "0"
                ).rstrip("."),
            }
        )
        return self.get_signal_gating_tuning_config()

    def get_global_broker_risk_caps(self) -> dict[str, float | int | None]:
        setting_map = self.get_setting_map()
        return {
            "global_max_live_open_notional_usd": self._get_optional_float(
                setting_map, "global_max_live_open_notional_usd"
            ),
            "global_max_live_daily_drawdown_usd": self._get_optional_float(
                setting_map, "global_max_live_daily_drawdown_usd"
            ),
            "global_max_live_daily_drawdown_pct": self._get_optional_float(
                setting_map, "global_max_live_daily_drawdown_pct"
            ),
            "global_max_live_order_count_per_day": self._get_optional_int(
                setting_map, "global_max_live_order_count_per_day"
            ),
        }

    def set_global_broker_risk_caps(
        self,
        *,
        max_live_open_notional_usd: float | None = None,
        max_live_daily_drawdown_usd: float | None = None,
        max_live_daily_drawdown_pct: float | None = None,
        max_live_order_count_per_day: int | None = None,
    ) -> dict[str, float | int | None]:
        self.set_settings(
            {
                "global_max_live_open_notional_usd": self._format_optional_number(
                    max_live_open_notional_usd
                ),
                "global_max_live_daily_drawdown_usd": self._format_optional_number(
                    max_live_daily_drawdown_usd
                ),
                "global_max_live_daily_drawdown_pct": self._format_optional_number(
                    max_live_daily_drawdown_pct
                ),
                "global_max_live_order_count_per_day": ""
                if max_live_order_count_per_day is None
                else str(int(max_live_order_count_per_day)),
            }
        )
        return self.get_global_broker_risk_caps()

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

    def set_plan_generation_active_config_version_id(
        self, config_version_id: int | None
    ) -> AppSetting:
        return self.set_setting(
            "plan_generation_active_config_version_id",
            "" if config_version_id is None else str(int(config_version_id)),
        )

    def get_plan_generation_tuning_settings(self) -> dict[str, object]:
        setting_map = self.get_setting_map()
        return {
            "active_config_version_id": self.get_plan_generation_active_config_version_id(),
            "auto_enabled": self._get_bool(
                setting_map, "plan_generation_tuning_auto_enabled", False
            ),
            "auto_promote_enabled": self._get_bool(
                setting_map, "plan_generation_tuning_auto_promote_enabled", False
            ),
            "min_actionable_resolved": self._get_int(
                setting_map, "plan_generation_tuning_min_actionable_resolved", 20
            ),
            "min_validation_resolved": self._get_int(
                setting_map, "plan_generation_tuning_min_validation_resolved", 8
            ),
        }

    def set_plan_generation_tuning_settings(
        self,
        *,
        auto_enabled: bool,
        auto_promote_enabled: bool,
        min_actionable_resolved: int,
        min_validation_resolved: int,
    ) -> dict[str, object]:
        self.set_settings(
            {
                "plan_generation_tuning_auto_enabled": str(bool(auto_enabled)).lower(),
                "plan_generation_tuning_auto_promote_enabled": str(
                    bool(auto_promote_enabled)
                ).lower(),
                "plan_generation_tuning_min_actionable_resolved": str(
                    max(1, int(min_actionable_resolved))
                ),
                "plan_generation_tuning_min_validation_resolved": str(
                    max(1, int(min_validation_resolved))
                ),
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
            "broker": (setting_map.get("order_execution_broker", "alpaca") or "alpaca")
            .strip()
            .lower(),
            "account_mode": (setting_map.get("order_execution_account_mode", "paper") or "paper")
            .strip()
            .lower(),
            "notional_per_plan": self._get_float(
                setting_map, "order_execution_notional_per_plan", 1000.0
            ),
        }

    def get_steering_config(self) -> dict[str, object]:
        setting_map = self.get_setting_map()
        return {
            "enabled": self._get_bool(setting_map, "steering_enabled", False),
            "dry_run": self._get_bool(setting_map, "steering_dry_run", True),
            "cancel_expired_pending_orders_enabled": self._get_bool(
                setting_map, "steering_cancel_expired_pending_orders_enabled", True
            ),
            "cancel_invalidated_pending_orders_enabled": self._get_bool(
                setting_map, "steering_cancel_invalidated_pending_orders_enabled", True
            ),
            "move_to_profit_enabled": self._get_bool(
                setting_map, "steering_move_to_profit_enabled", True
            ),
            "close_on_severe_invalidation_enabled": self._get_bool(
                setting_map, "steering_close_on_severe_invalidation_enabled", True
            ),
            "tighten_on_deterioration_enabled": self._get_bool(
                setting_map, "steering_tighten_on_deterioration_enabled", True
            ),
            "lower_tp_on_weakness_enabled": self._get_bool(
                setting_map, "steering_lower_tp_on_weakness_enabled", True
            ),
            "pending_expiration_grace_minutes": self._get_int(
                setting_map, "steering_pending_expiration_grace_minutes", 5
            ),
            "pending_min_confidence_percent": self._get_float(
                setting_map, "steering_pending_min_confidence_percent", 55.0
            ),
            "pending_invalidation_required_signals": self._get_int(
                setting_map, "steering_pending_invalidation_required_signals", 2
            ),
            "pending_price_chase_limit_percent": self._get_float(
                setting_map, "steering_pending_price_chase_limit_percent", 1.0
            ),
            "breakeven_trigger_percent": self._get_float(
                setting_map, "steering_breakeven_trigger_percent", 0.75
            ),
            "min_profit_lock_percent": self._get_float(
                setting_map, "steering_min_profit_lock_percent", 0.10
            ),
            "position_close_confidence_percent": self._get_float(
                setting_map, "steering_position_close_confidence_percent", 40.0
            ),
            "position_close_required_signals": self._get_int(
                setting_map, "steering_position_close_required_signals", 3
            ),
            "position_min_hold_confidence_percent": self._get_float(
                setting_map, "steering_position_min_hold_confidence_percent", 50.0
            ),
            "position_deterioration_required_signals": self._get_int(
                setting_map, "steering_position_deterioration_required_signals", 2
            ),
            "deterioration_stop_cushion_percent": self._get_float(
                setting_map, "steering_deterioration_stop_cushion_percent", 0.35
            ),
            "weakened_thesis_tp_cushion_percent": self._get_float(
                setting_map, "steering_weakened_thesis_tp_cushion_percent", 0.50
            ),
            "min_tp_distance_percent": self._get_float(
                setting_map, "steering_min_tp_distance_percent", 0.10
            ),
            "max_reconciliation_age_minutes": self._get_int(
                setting_map, "steering_max_reconciliation_age_minutes", 30
            ),
            "min_reviewed_dry_run_decisions_before_enable": self._get_int(
                setting_map, "steering_min_reviewed_dry_run_decisions_before_enable", 30
            ),
            "min_reviewed_dry_run_amendments_before_enable": self._get_int(
                setting_map, "steering_min_reviewed_dry_run_amendments_before_enable", 10
            ),
            "min_reviewed_dry_run_close_now_before_enable": self._get_int(
                setting_map, "steering_min_reviewed_dry_run_close_now_before_enable", 10
            ),
        }

    def set_steering_config(
        self,
        *,
        enabled: bool,
        dry_run: bool,
        cancel_expired_pending_orders_enabled: bool,
        cancel_invalidated_pending_orders_enabled: bool,
        move_to_profit_enabled: bool,
        close_on_severe_invalidation_enabled: bool,
        tighten_on_deterioration_enabled: bool,
        lower_tp_on_weakness_enabled: bool,
        pending_expiration_grace_minutes: int,
        pending_min_confidence_percent: float,
        pending_invalidation_required_signals: int,
        pending_price_chase_limit_percent: float,
        breakeven_trigger_percent: float,
        min_profit_lock_percent: float,
        position_close_confidence_percent: float,
        position_close_required_signals: int,
        position_min_hold_confidence_percent: float,
        position_deterioration_required_signals: int,
        deterioration_stop_cushion_percent: float,
        weakened_thesis_tp_cushion_percent: float,
        min_tp_distance_percent: float,
        max_reconciliation_age_minutes: int = 30,
        min_reviewed_dry_run_decisions_before_enable: int = 30,
        min_reviewed_dry_run_amendments_before_enable: int = 10,
        min_reviewed_dry_run_close_now_before_enable: int = 10,
    ) -> dict[str, object]:
        self.set_settings(
            {
                "steering_enabled": str(bool(enabled)).lower(),
                "steering_dry_run": str(bool(dry_run)).lower(),
                "steering_cancel_expired_pending_orders_enabled": str(
                    bool(cancel_expired_pending_orders_enabled)
                ).lower(),
                "steering_cancel_invalidated_pending_orders_enabled": str(
                    bool(cancel_invalidated_pending_orders_enabled)
                ).lower(),
                "steering_move_to_profit_enabled": str(bool(move_to_profit_enabled)).lower(),
                "steering_close_on_severe_invalidation_enabled": str(
                    bool(close_on_severe_invalidation_enabled)
                ).lower(),
                "steering_tighten_on_deterioration_enabled": str(
                    bool(tighten_on_deterioration_enabled)
                ).lower(),
                "steering_lower_tp_on_weakness_enabled": str(
                    bool(lower_tp_on_weakness_enabled)
                ).lower(),
                "steering_pending_expiration_grace_minutes": str(
                    max(0, int(pending_expiration_grace_minutes))
                ),
                "steering_pending_min_confidence_percent": f"{float(pending_min_confidence_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_pending_invalidation_required_signals": str(
                    max(0, int(pending_invalidation_required_signals))
                ),
                "steering_pending_price_chase_limit_percent": f"{float(pending_price_chase_limit_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_breakeven_trigger_percent": f"{float(breakeven_trigger_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_min_profit_lock_percent": f"{float(min_profit_lock_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_position_close_confidence_percent": f"{float(position_close_confidence_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_position_close_required_signals": str(
                    max(0, int(position_close_required_signals))
                ),
                "steering_position_min_hold_confidence_percent": f"{float(position_min_hold_confidence_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_position_deterioration_required_signals": str(
                    max(0, int(position_deterioration_required_signals))
                ),
                "steering_deterioration_stop_cushion_percent": f"{float(deterioration_stop_cushion_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_weakened_thesis_tp_cushion_percent": f"{float(weakened_thesis_tp_cushion_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_min_tp_distance_percent": f"{float(min_tp_distance_percent):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "steering_max_reconciliation_age_minutes": str(
                    max(1, int(max_reconciliation_age_minutes))
                ),
                "steering_min_reviewed_dry_run_decisions_before_enable": str(
                    max(0, int(min_reviewed_dry_run_decisions_before_enable))
                ),
                "steering_min_reviewed_dry_run_amendments_before_enable": str(
                    max(0, int(min_reviewed_dry_run_amendments_before_enable))
                ),
                "steering_min_reviewed_dry_run_close_now_before_enable": str(
                    max(0, int(min_reviewed_dry_run_close_now_before_enable))
                ),
            }
        )
        return self.get_steering_config()

    def get_risk_management_config(self) -> dict[str, object]:
        setting_map = self.get_setting_map()
        return {
            "enabled": self._get_bool(setting_map, "risk_management_enabled", True),
            "halt_enabled": self._get_bool(setting_map, "risk_halt_enabled", False),
            "halt_reason": (setting_map.get("risk_halt_reason", "") or "").strip(),
            "max_daily_realized_loss_usd": self._get_float(
                setting_map, "risk_max_daily_realized_loss_usd", 50.0
            ),
            "max_open_positions": self._get_int(setting_map, "risk_max_open_positions", 3),
            "max_open_notional_usd": self._get_float(
                setting_map, "risk_max_open_notional_usd", 3000.0
            ),
            "max_position_notional_usd": self._get_float(
                setting_map, "risk_max_position_notional_usd", 1000.0
            ),
            "max_same_ticker_open_positions": self._get_int(
                setting_map, "risk_max_same_ticker_open_positions", 1
            ),
            "max_consecutive_losses": self._get_int(setting_map, "risk_max_consecutive_losses", 3),
        }

    def set_risk_management_config(
        self,
        *,
        enabled: bool,
        max_daily_realized_loss_usd: float,
        max_open_positions: int,
        max_open_notional_usd: float,
        max_position_notional_usd: float,
        max_same_ticker_open_positions: int,
        max_consecutive_losses: int,
    ) -> dict[str, object]:
        self.set_settings(
            {
                "risk_management_enabled": str(bool(enabled)).lower(),
                "risk_max_daily_realized_loss_usd": f"{float(max_daily_realized_loss_usd):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "risk_max_open_positions": str(max(0, int(max_open_positions))),
                "risk_max_open_notional_usd": f"{float(max_open_notional_usd):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "risk_max_position_notional_usd": f"{float(max_position_notional_usd):.4f}".rstrip(
                    "0"
                ).rstrip("."),
                "risk_max_same_ticker_open_positions": str(
                    max(0, int(max_same_ticker_open_positions))
                ),
                "risk_max_consecutive_losses": str(max(0, int(max_consecutive_losses))),
            }
        )
        return self.get_risk_management_config()

    def set_risk_halt(self, *, enabled: bool, reason: str = "") -> dict[str, object]:
        self.set_settings(
            {"risk_halt_enabled": str(bool(enabled)).lower(), "risk_halt_reason": reason.strip()}
        )
        return self.get_risk_management_config()

    def set_order_execution_config(
        self,
        *,
        enabled: bool,
        broker: str = "alpaca",
        account_mode: str = "paper",
        notional_per_plan: float = 1000.0,
    ) -> dict[str, object]:
        self.set_settings(
            {
                "order_execution_enabled": str(bool(enabled)).lower(),
                "order_execution_broker": broker.strip().lower() or "alpaca",
                "order_execution_account_mode": account_mode.strip().lower() or "paper",
                "order_execution_notional_per_plan": f"{float(notional_per_plan):.4f}".rstrip(
                    "0"
                ).rstrip("."),
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
    def _get_optional_float(setting_map: dict[str, str], key: str) -> float | None:
        raw_value = (setting_map.get(key, "") or "").strip()
        if not raw_value:
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_int(setting_map: dict[str, str], key: str, default: int) -> int:
        raw_value = setting_map.get(key, str(default))
        try:
            return int((raw_value or "").strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_optional_int(setting_map: dict[str, str], key: str) -> int | None:
        raw_value = (setting_map.get(key, "") or "").strip()
        if not raw_value:
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_optional_number(value: float | None) -> str:
        if value is None:
            return ""
        return f"{float(value):.4f}".rstrip("0").rstrip(".")

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
        return [
            ProviderCredential(provider=item.provider, api_key=item.api_key, api_secret="")
            for item in self.list_provider_credentials()
        ]

    def get_provider_credential_map(self) -> dict[str, ProviderCredential]:
        return {item.provider: item for item in self.list_provider_credentials()}

    def upsert_provider_credential(
        self, provider: str, api_key: str, api_secret: str
    ) -> ProviderCredential:
        provider = provider.strip().lower()
        api_key = api_key.strip()
        api_secret = api_secret.strip()
        if not provider:
            raise ValueError("provider is required")
        if not api_key:
            raise ValueError("api key is required when creating or updating a provider credential")
        requires_secret = provider == "alpaca"
        record = self.session.get(ProviderCredentialRecord, provider)
        if record is None:
            if requires_secret and not api_secret:
                raise ValueError(
                    "api secret is required when creating an alpaca provider credential"
                )
            record = ProviderCredentialRecord(
                provider=provider,
                api_key=credential_cipher.encrypt(api_key),
                api_secret=credential_cipher.encrypt(api_secret)
                if api_secret
                else credential_cipher.encrypt(""),
            )
            self.session.add(record)
        else:
            record.api_key = credential_cipher.encrypt(api_key)
            if api_secret:
                record.api_secret = credential_cipher.encrypt(api_secret)
            elif requires_secret and not record.api_secret:
                raise ValueError(
                    "api secret is required when creating an alpaca provider credential"
                )
        self.session.commit()
        return ProviderCredential(
            provider=record.provider,
            api_key=credential_cipher.decrypt(record.api_key),
            api_secret=credential_cipher.decrypt(record.api_secret),
        )
