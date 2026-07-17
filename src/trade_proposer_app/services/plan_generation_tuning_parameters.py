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
        key="global.execution_confidence_floor_percent",
        label="Execution confidence floor",
        default=60.0,
        minimum=0.0,
        maximum=90.0,
        exploration_min=45.0,
        exploration_max=70.0,
        step=5.0,
        category="selectivity",
        description="Minimum broker-calibrated confidence required for a plan to be broker-executable.",
        validation_depth="rescore_only",
        validation_depth_reason="Execution-floor changes only rescore broker execution eligibility against already generated plan evidence.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.actionable_confidence_floor_percent",
        label="Legacy actionable confidence floor",
        default=60.0,
        minimum=0.0,
        maximum=90.0,
        exploration_min=40.0,
        exploration_max=70.0,
        step=5.0,
        category="selectivity",
        description="Compatibility alias for the execution confidence floor; new policies should use global.execution_confidence_floor_percent.",
        validation_depth="rescore_only",
        validation_depth_reason="Legacy actionability-floor changes only rescore broker execution eligibility against already generated plan evidence.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.research_plan_floor_percent",
        label="Research plan confidence floor",
        default=45.0,
        minimum=0.0,
        maximum=90.0,
        exploration_min=25.0,
        exploration_max=60.0,
        step=5.0,
        category="selectivity",
        description="Lower calibrated-confidence floor for full non-executing research plans with trade geometry and outcome tracking.",
        validation_depth="rescore_only",
        validation_depth_reason="Research-floor changes only reclassify existing plan evidence into execution/research/shadow tiers.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.shadow_tracking_floor_percent",
        label="Shadow tracking confidence floor",
        default=35.0,
        minimum=0.0,
        maximum=90.0,
        exploration_min=15.0,
        exploration_max=50.0,
        step=5.0,
        category="selectivity",
        description="Lower calibrated-confidence floor for non-executing shadow observations used to measure rejected-plan opportunity.",
        validation_depth="rescore_only",
        validation_depth_reason="Shadow-floor changes only reclassify existing plan evidence into execution/research/shadow tiers.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.research_plan_quota_per_run",
        label="Research plan quota per run",
        default=10.0,
        minimum=0.0,
        maximum=200.0,
        exploration_min=0.0,
        exploration_max=50.0,
        step=5.0,
        category="selectivity",
        description="Maximum number of non-executing research plans emitted per orchestration run.",
        validation_depth="rescore_only",
        validation_depth_reason="Research quota changes only reclassify generated threshold misses and do not change upstream evidence.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="global.shadow_tracking_quota_per_run",
        label="Shadow tracking quota per run",
        default=25.0,
        minimum=0.0,
        maximum=500.0,
        exploration_min=0.0,
        exploration_max=100.0,
        step=5.0,
        category="selectivity",
        description="Maximum number of lower-confidence shadow observations retained per orchestration run.",
        validation_depth="rescore_only",
        validation_depth_reason="Shadow quota changes only reclassify generated threshold misses and do not change upstream evidence.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.research_floor_delta_percent",
        label="Setup-family research floor delta",
        default=0.0,
        minimum=-25.0,
        maximum=25.0,
        exploration_min=-10.0,
        exploration_max=10.0,
        step=5.0,
        category="selectivity",
        description="Setup-family adjustment applied to the research plan floor until family-specific keys are added.",
        validation_depth="rescore_only",
        validation_depth_reason="Research-floor deltas only reclassify existing generated evidence by setup family.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="setup_family.shadow_quota_weight",
        label="Setup-family shadow quota weight",
        default=1.0,
        minimum=0.0,
        maximum=3.0,
        exploration_min=0.5,
        exploration_max=2.0,
        step=0.25,
        category="selectivity",
        description="Reserved multiplier for future per-family shadow quota allocation; currently persisted for policy visibility.",
        validation_depth="rescore_only",
        validation_depth_reason="Shadow quota weighting only affects research/shadow classification, not upstream signal generation.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="phantom_selectivity.tailwind_floor_delta_percent",
        label="Phantom tailwind floor delta",
        default=0.0,
        minimum=-25.0,
        maximum=25.0,
        exploration_min=-15.0,
        exploration_max=10.0,
        step=5.0,
        category="selectivity",
        description="Research-only actionability-floor adjustment for phantom rows whose stored transmission context is tailwind.",
        validation_depth="rescore_only",
        validation_depth_reason="Phantom selectivity context deltas only rescore existing phantom replay evidence and require candidate-specific replay before promotion.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="phantom_selectivity.headwind_floor_delta_percent",
        label="Phantom headwind floor delta",
        default=0.0,
        minimum=-25.0,
        maximum=25.0,
        exploration_min=-10.0,
        exploration_max=15.0,
        step=5.0,
        category="selectivity",
        description="Research-only actionability-floor adjustment for phantom rows whose stored transmission context is headwind.",
        validation_depth="rescore_only",
        validation_depth_reason="Phantom selectivity context deltas only rescore existing phantom replay evidence and require candidate-specific replay before promotion.",
    ),
    PlanGenerationTuningParameterDefinition(
        key="phantom_selectivity.volatility_floor_slope_percent",
        label="Phantom volatility floor slope",
        default=0.0,
        minimum=-30.0,
        maximum=30.0,
        exploration_min=-15.0,
        exploration_max=15.0,
        step=5.0,
        category="selectivity",
        description="Research-only floor slope applied around the midpoint of stored cheap-scan volatility scores for phantom rows.",
        validation_depth="rescore_only",
        validation_depth_reason="Phantom selectivity volatility slope only rescores existing phantom replay evidence and requires candidate-specific replay before promotion.",
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
        candidate_budget=4,
        parameter_keys=(
            "global.execution_confidence_floor_percent",
            "global.research_plan_floor_percent",
            "global.shadow_tracking_floor_percent",
            "global.research_plan_quota_per_run",
        ),
        description="Try execution/research/shadow floors second because they control live safety separately from learning sample collection.",
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
