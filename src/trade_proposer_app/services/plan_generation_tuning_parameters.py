from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ValidationDepth = Literal["rescore_only", "frozen_input_plan_regeneration", "full_orchestration_replay"]

_VALIDATION_DEPTH_RANK: dict[ValidationDepth, int] = {
    "rescore_only": 0,
    "frozen_input_plan_regeneration": 1,
    "full_orchestration_replay": 2,
}


@dataclass(frozen=True, slots=True)
class PlanGenerationTuningParameterDefinition:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    exploration_min: float
    exploration_max: float
    step: float
    category: str
    description: str
    validation_depth: ValidationDepth
    validation_depth_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "exploration_min": self.exploration_min,
            "exploration_max": self.exploration_max,
            "step": self.step,
            "category": self.category,
            "description": self.description,
            "validation_depth": self.validation_depth,
            "validation_depth_reason": self.validation_depth_reason,
        }


@dataclass(frozen=True, slots=True)
class PlanGenerationExplorationCampaign:
    name: str
    priority: int
    candidate_budget: int
    parameter_keys: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "priority": self.priority,
            "candidate_budget": self.candidate_budget,
            "parameter_keys": list(self.parameter_keys),
            "description": self.description,
        }


PARAMETER_DEFINITIONS: tuple[PlanGenerationTuningParameterDefinition, ...] = (
    PlanGenerationTuningParameterDefinition(
        key="global.entry_band_risk_fraction",
        label="Global entry band as fraction of baseline risk distance",
        default=0.0,
        minimum=0.0,
        maximum=0.5,
        exploration_min=0.0,
        exploration_max=0.25,
        step=0.05,
        category="entry",
        description="Expands entry into a bounded range around the baseline entry using the baseline risk distance.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Entry geometry changes require regenerating plans from frozen upstream evidence, but do not require rerunning cheap scan or signal generation.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.entry_band_multiplier",
        label="Setup-family entry band multiplier",
        default=1.0,
        minimum=0.8,
        maximum=1.25,
        exploration_min=0.9,
        exploration_max=1.12,
        step=0.05,
        category="entry",
        description="Scales the global entry band before family-specific entry framing is applied.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Entry geometry changes require regenerating plans from frozen upstream evidence, but do not require rerunning cheap scan or signal generation.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.headwind_stop_multiplier",
        label="Headwind stop multiplier",
        default=0.92,
        minimum=0.75,
        maximum=1.1,
        exploration_min=0.84,
        exploration_max=1.02,
        step=0.02,
        category="risk",
        description="Multiplies the stop distance when transmission context_bias is headwind.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Stop geometry changes require regenerating plans and resolving outcomes against reused local outcome bars.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.actionable_confidence_floor_percent",
        label="Actionable confidence floor",
        default=60.0,
        minimum=0.0,
        maximum=90.0,
        exploration_min=40.0,
        exploration_max=70.0,
        step=5.0,
        category="selectivity",
        description="Raises the minimum calibrated confidence required for a plan to stay actionable.",
        validation_depth="rescore_only",
        validation_depth_reason="A standalone final actionability-floor change can reuse generated plan geometry and rescore actionable eligibility.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.volatility_stop_multiplier",
        label="Volatility stop multiplier",
        default=0.12,
        minimum=0.0,
        maximum=0.4,
        exploration_min=0.0,
        exploration_max=0.25,
        step=0.04,
        category="risk",
        description="Scales stop distance using the stored volatility proxy so noisy setups can breathe more.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Stop geometry changes require regenerating plans and resolving outcomes against reused local outcome bars.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.breakout.stop_distance_multiplier",
        label="Breakout stop distance multiplier",
        default=0.85,
        minimum=0.6,
        maximum=1.3,
        exploration_min=0.65,
        exploration_max=1.05,
        step=0.05,
        category="risk",
        description="Scales breakout/breakdown stop distance relative to baseline recommendation risk.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Setup-family stop geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.breakout.take_profit_distance_multiplier",
        label="Breakout take-profit distance multiplier",
        default=1.12,
        minimum=0.7,
        maximum=1.6,
        exploration_min=0.95,
        exploration_max=1.45,
        step=0.05,
        category="reward",
        description="Scales breakout/breakdown take-profit distance relative to baseline recommendation reward.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Take-profit geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.mean_reversion.stop_distance_multiplier",
        label="Mean-reversion stop distance multiplier",
        default=1.1,
        minimum=0.7,
        maximum=1.5,
        exploration_min=0.88,
        exploration_max=1.32,
        step=0.05,
        category="risk",
        description="Scales mean-reversion stop distance relative to baseline recommendation risk.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Setup-family stop geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.mean_reversion.take_profit_distance_multiplier",
        label="Mean-reversion take-profit distance multiplier",
        default=0.88,
        minimum=0.6,
        maximum=1.4,
        exploration_min=0.72,
        exploration_max=1.08,
        step=0.05,
        category="reward",
        description="Scales mean-reversion take-profit distance relative to baseline recommendation reward.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Take-profit geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.catalyst_follow_through.take_profit_distance_multiplier",
        label="Catalyst follow-through take-profit distance multiplier",
        default=1.18,
        minimum=0.8,
        maximum=1.8,
        exploration_min=1.05,
        exploration_max=1.5,
        step=0.05,
        category="reward",
        description="Scales catalyst follow-through take-profit distance relative to baseline recommendation reward.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Take-profit geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
        label="Macro beneficiary/loser take-profit distance multiplier",
        default=1.08,
        minimum=0.8,
        maximum=1.5,
        exploration_min=1.0,
        exploration_max=1.3,
        step=0.05,
        category="reward",
        description="Scales macro beneficiary/loser take-profit distance relative to baseline recommendation reward.",
        validation_depth="frozen_input_plan_regeneration",
        validation_depth_reason="Take-profit geometry changes require regenerating plans and resolving outcomes from frozen inputs.",
    ),
)

PARAMETER_DEFAULTS: dict[str, float] = {item.key: item.default for item in PARAMETER_DEFINITIONS}
PARAMETER_BY_KEY: dict[str, PlanGenerationTuningParameterDefinition] = {item.key: item for item in PARAMETER_DEFINITIONS}


def candidate_validation_depth(changed_keys: list[str] | tuple[str, ...] | set[str]) -> dict[str, object]:
    """Return the cheapest safe validation depth for a candidate.

    Mixed candidates inherit the deepest required recomputation boundary. Unknown keys fail
    closed as full orchestration and are reported for schema validation to reject earlier.
    """
    normalized_keys = sorted({str(key) for key in changed_keys if str(key)})
    if not normalized_keys:
        return {
            "validation_depth": "rescore_only",
            "validation_depth_reason": "Baseline/no-op candidate does not require recomputation.",
            "unknown_keys": [],
            "parameter_depths": {},
        }
    selected_depth: ValidationDepth = "rescore_only"
    unknown_keys: list[str] = []
    parameter_depths: dict[str, dict[str, str]] = {}
    reasons: list[str] = []
    for key in normalized_keys:
        definition = PARAMETER_BY_KEY.get(key)
        if definition is None:
            selected_depth = "full_orchestration_replay"
            unknown_keys.append(key)
            parameter_depths[key] = {
                "validation_depth": "full_orchestration_replay",
                "validation_depth_reason": "Unknown parameter key; fail closed until schema validation rejects or maps it.",
            }
            reasons.append(f"{key}: unknown key requires fail-closed handling")
            continue
        parameter_depths[key] = {
            "validation_depth": definition.validation_depth,
            "validation_depth_reason": definition.validation_depth_reason,
        }
        reasons.append(f"{key}: {definition.validation_depth_reason}")
        if _VALIDATION_DEPTH_RANK[definition.validation_depth] > _VALIDATION_DEPTH_RANK[selected_depth]:
            selected_depth = definition.validation_depth
    return {
        "validation_depth": selected_depth,
        "validation_depth_reason": " ".join(reasons),
        "unknown_keys": unknown_keys,
        "parameter_depths": parameter_depths,
    }


EXPLORATION_CAMPAIGNS: tuple[PlanGenerationExplorationCampaign, ...] = (
    PlanGenerationExplorationCampaign(
        name="entry_calibration",
        priority=1,
        candidate_budget=4,
        parameter_keys=(
            "global.entry_band_risk_fraction",
            "setup_family.entry_band_multiplier",
        ),
        description="Try the entry band first because it changes actionable eligibility and family-specific entry offset before the rest of the price framing.",
    ),
    PlanGenerationExplorationCampaign(
        name="selectivity",
        priority=2,
        candidate_budget=1,
        parameter_keys=("global.actionable_confidence_floor_percent",),
        description="Try the confidence floor second because it can keep weak setups out of the actionable set.",
    ),
    PlanGenerationExplorationCampaign(
        name="risk_protection",
        priority=3,
        candidate_budget=4,
        parameter_keys=(
            "global.headwind_stop_multiplier",
            "global.volatility_stop_multiplier",
            "setup_family.breakout.stop_distance_multiplier",
            "setup_family.mean_reversion.stop_distance_multiplier",
        ),
        description="Try the downside-protection knobs third because they preserve the best entries while letting noisy setups breathe or tightening loss behavior.",
    ),
    PlanGenerationExplorationCampaign(
        name="reward_expansion",
        priority=4,
        candidate_budget=4,
        parameter_keys=(
            "setup_family.breakout.take_profit_distance_multiplier",
            "setup_family.mean_reversion.take_profit_distance_multiplier",
            "setup_family.catalyst_follow_through.take_profit_distance_multiplier",
            "setup_family.macro_beneficiary_loser.take_profit_distance_multiplier",
        ),
        description="Try the reward-side multipliers fourth because they shape the payoff distribution after the entry and stop remain stable.",
    ),
)


def parameter_definitions() -> list[dict[str, object]]:
    return [item.to_dict() for item in PARAMETER_DEFINITIONS]


def exploration_campaigns() -> list[dict[str, object]]:
    return [item.to_dict() for item in EXPLORATION_CAMPAIGNS]


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
