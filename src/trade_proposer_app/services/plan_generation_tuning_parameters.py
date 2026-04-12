from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanGenerationTuningParameterDefinition:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    step: float
    category: str
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "category": self.category,
            "description": self.description,
        }


PARAMETER_DEFINITIONS: tuple[PlanGenerationTuningParameterDefinition, ...] = (
    PlanGenerationTuningParameterDefinition(
        key="global.entry_band_risk_fraction",
        label="Global entry band as fraction of baseline risk distance",
        default=0.0,
        minimum=0.0,
        maximum=0.5,
        step=0.05,
        category="entry",
        description="Expands entry into a bounded range around the baseline entry using the baseline risk distance.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.headwind_stop_multiplier",
        label="Headwind stop multiplier",
        default=0.92,
        minimum=0.75,
        maximum=1.1,
        step=0.02,
        category="risk",
        description="Multiplies the stop distance when transmission context_bias is headwind.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.breakout.stop_distance_multiplier",
        label="Breakout stop distance multiplier",
        default=0.85,
        minimum=0.6,
        maximum=1.3,
        step=0.05,
        category="risk",
        description="Scales breakout/breakdown stop distance relative to baseline recommendation risk.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.breakout.take_profit_distance_multiplier",
        label="Breakout take-profit distance multiplier",
        default=1.12,
        minimum=0.7,
        maximum=1.6,
        step=0.05,
        category="reward",
        description="Scales breakout/breakdown take-profit distance relative to baseline recommendation reward.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.mean_reversion.stop_distance_multiplier",
        label="Mean-reversion stop distance multiplier",
        default=1.1,
        minimum=0.7,
        maximum=1.5,
        step=0.05,
        category="risk",
        description="Scales mean-reversion stop distance relative to baseline recommendation risk.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.mean_reversion.take_profit_distance_multiplier",
        label="Mean-reversion take-profit distance multiplier",
        default=0.88,
        minimum=0.6,
        maximum=1.4,
        step=0.05,
        category="reward",
        description="Scales mean-reversion take-profit distance relative to baseline recommendation reward.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.catalyst_follow_through.take_profit_distance_multiplier",
        label="Catalyst follow-through take-profit distance multiplier",
        default=1.18,
        minimum=0.8,
        maximum=1.8,
        step=0.05,
        category="reward",
        description="Scales catalyst follow-through take-profit distance relative to baseline recommendation reward.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
        label="Macro beneficiary/loser take-profit distance multiplier",
        default=1.08,
        minimum=0.8,
        maximum=1.5,
        step=0.05,
        category="reward",
        description="Scales macro beneficiary/loser take-profit distance relative to baseline recommendation reward.",
    ),
)

PARAMETER_DEFAULTS: dict[str, float] = {item.key: item.default for item in PARAMETER_DEFINITIONS}
PARAMETER_BY_KEY: dict[str, PlanGenerationTuningParameterDefinition] = {item.key: item for item in PARAMETER_DEFINITIONS}


def parameter_definitions() -> list[dict[str, object]]:
    return [item.to_dict() for item in PARAMETER_DEFINITIONS]


def normalize_plan_generation_tuning_config(config: dict[str, object] | None) -> dict[str, float]:
    normalized = dict(PARAMETER_DEFAULTS)
    if not config:
        return normalized
    for key, definition in PARAMETER_BY_KEY.items():
        raw_value = config.get(key, definition.default)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = definition.default
        value = max(definition.minimum, min(definition.maximum, value))
        normalized[key] = round(value, 4)
    return normalized
