from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config


@dataclass(frozen=True)
class SignalGatingPolicy:
    threshold_offset: float = 0.0
    confidence_adjustment: float = 0.0
    near_miss_gap_cutoff: float = 0.0
    shortlist_aggressiveness: float = 0.0
    degraded_penalty: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "threshold_offset": self.threshold_offset,
            "confidence_adjustment": self.confidence_adjustment,
            "near_miss_gap_cutoff": self.near_miss_gap_cutoff,
            "shortlist_aggressiveness": self.shortlist_aggressiveness,
            "degraded_penalty": self.degraded_penalty,
        }


@dataclass(frozen=True)
class TradeDecisionPolicy:
    """Normalized strategy-selection policy independent from account risk limits."""

    policy_id: str
    confidence_threshold: float
    allow_longs: bool = True
    allow_shorts: bool = True
    allowed_setup_families: tuple[str, ...] = ()
    blocked_setup_families: tuple[str, ...] = ()
    signal_gating: SignalGatingPolicy = field(default_factory=SignalGatingPolicy)
    plan_generation_config: dict[str, float] = field(default_factory=dict)
    plan_generation_config_version_id: int | None = None

    def effective_confidence_threshold(self) -> float:
        return max(0.0, min(100.0, self.confidence_threshold + self.signal_gating.threshold_offset))

    def setup_family_allowed(self, setup_family: str | None) -> bool:
        normalized = str(setup_family or "uncategorized").strip().lower() or "uncategorized"
        if self.allowed_setup_families and normalized not in self.allowed_setup_families:
            return False
        return normalized not in self.blocked_setup_families

    def action_allowed(self, action: str | None) -> bool:
        normalized = str(action or "").strip().lower()
        if normalized == "long":
            return self.allow_longs
        if normalized == "short":
            return self.allow_shorts
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "confidence_threshold": self.confidence_threshold,
            "effective_confidence_threshold": self.effective_confidence_threshold(),
            "allow_longs": self.allow_longs,
            "allow_shorts": self.allow_shorts,
            "allowed_setup_families": list(self.allowed_setup_families),
            "blocked_setup_families": list(self.blocked_setup_families),
            "signal_gating": self.signal_gating.to_dict(),
            "plan_generation_config": dict(self.plan_generation_config),
            "plan_generation_config_version_id": self.plan_generation_config_version_id,
        }


class TradeDecisionPolicyService:
    """Builds the active trade-selection policy from persisted app settings.

    This service deliberately excludes broker/account risk limits. Risk remains the
    responsibility of BrokerRiskManager and is applied after a plan is selected.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = SettingsRepository(session)
        self.plan_generation = PlanGenerationTuningRepository(session)

    def active_policy(self) -> TradeDecisionPolicy:
        signal_gating = self.settings.get_signal_gating_tuning_config()
        config_version_id = self.settings.get_plan_generation_active_config_version_id()
        plan_generation_config = self.settings.get_plan_generation_active_config(self.plan_generation)
        return TradeDecisionPolicy(
            policy_id=f"settings-active:{config_version_id or 'baseline'}",
            confidence_threshold=self.settings.get_confidence_threshold(),
            signal_gating=SignalGatingPolicy(
                threshold_offset=self._float(signal_gating.get("threshold_offset")),
                confidence_adjustment=self._float(signal_gating.get("confidence_adjustment")),
                near_miss_gap_cutoff=self._float(signal_gating.get("near_miss_gap_cutoff")),
                shortlist_aggressiveness=self._float(signal_gating.get("shortlist_aggressiveness")),
                degraded_penalty=self._float(signal_gating.get("degraded_penalty")),
            ),
            plan_generation_config=normalize_plan_generation_tuning_config(plan_generation_config),
            plan_generation_config_version_id=config_version_id,
        )

    @staticmethod
    def _float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
