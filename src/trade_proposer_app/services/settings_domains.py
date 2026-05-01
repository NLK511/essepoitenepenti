from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.settings import SettingsRepository


@dataclass(frozen=True)
class StrategySettings:
    confidence_threshold: float
    signal_gating: dict[str, float]
    plan_generation_tuning: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "confidence_threshold": self.confidence_threshold,
            "signal_gating": dict(self.signal_gating),
            "plan_generation_tuning": dict(self.plan_generation_tuning),
        }


@dataclass(frozen=True)
class RiskSettings:
    risk_management: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"risk_management": dict(self.risk_management)}


@dataclass(frozen=True)
class ExecutionSettings:
    broker_order_execution: dict[str, object]
    evaluation_realism: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "broker_order_execution": dict(self.broker_order_execution),
            "evaluation_realism": dict(self.evaluation_realism),
        }


@dataclass(frozen=True)
class OperatorSettings:
    summary: dict[str, object]
    social: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": dict(self.summary),
            "social": dict(self.social),
        }


class SettingsDomainService:
    """Typed domain views over the legacy key/value settings repository."""

    def __init__(self, session: Session | None = None, repository: SettingsRepository | None = None) -> None:
        if repository is None and session is None:
            raise ValueError("session or repository is required")
        self.repository = repository or SettingsRepository(session)  # type: ignore[arg-type]

    def strategy_settings(self) -> StrategySettings:
        return StrategySettings(
            confidence_threshold=self.repository.get_confidence_threshold(),
            signal_gating=self.repository.get_signal_gating_tuning_config(),
            plan_generation_tuning=self.repository.get_plan_generation_tuning_settings(),
        )

    def risk_settings(self) -> RiskSettings:
        return RiskSettings(risk_management=self.repository.get_risk_management_config())

    def execution_settings(self) -> ExecutionSettings:
        return ExecutionSettings(
            broker_order_execution=self.repository.get_order_execution_config(),
            evaluation_realism=self.repository.get_evaluation_realism_config(),
        )

    def operator_settings(self) -> OperatorSettings:
        return OperatorSettings(
            summary=self.repository.get_summary_settings(),
            social=self.repository.get_social_settings(),
        )
