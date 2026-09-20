from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class PhantomSelectivityPromotionPreflightGates:
    min_selection_rows: int = 100
    min_selection_dates: int = 20
    min_selection_ev_per_observation: float = 0.0
    min_selection_win_rate_lift_pct: float = 0.0

    def payload(self) -> dict[str, object]:
        return {
            "min_selection_rows": self.min_selection_rows,
            "min_selection_dates": self.min_selection_dates,
            "min_selection_ev_per_observation": self.min_selection_ev_per_observation,
            "min_selection_win_rate_lift_pct": self.min_selection_win_rate_lift_pct,
        }


def build_phantom_selectivity_promotion_preflight(
    *,
    candidate_replay: dict[str, object],
    evidence_lineage: dict[str, object] | None = None,
    driver_quality: dict[str, object] | None = None,
    source_artifacts: dict[str, str] | None = None,
    gates: PhantomSelectivityPromotionPreflightGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or PhantomSelectivityPromotionPreflightGates()
    blockers: list[str] = []
    warnings: list[str] = []

    if candidate_replay.get("verdict") != "promotion_candidate_ready":
        blockers.append("candidate_replay_not_promotion_ready")
    if candidate_replay.get("promotion_candidate_ready") is not True:
        blockers.append("candidate_replay_promotion_flag_false")

    union = _dict(candidate_replay.get("combined_union"))
    if union.get("promotion_ready") is not True:
        blockers.append("combined_union_not_promotion_ready")
    for blocker in list(union.get("promotion_blockers") or []):
        blockers.append(f"combined_union:{blocker}")

    selection = _dict(union.get("selection"))
    if int(selection.get("count") or 0) < gates.min_selection_rows:
        blockers.append("selection_rows_below_preflight_minimum")
    if int(selection.get("distinct_date_count") or 0) < gates.min_selection_dates:
        blockers.append("selection_dates_below_preflight_minimum")
    if (
        float(selection.get("expected_value_per_observation") or 0.0)
        <= gates.min_selection_ev_per_observation
    ):
        blockers.append("selection_ev_per_observation_not_positive")
    if (
        float(union.get("selection_win_rate_lift_pct") or 0.0)
        <= gates.min_selection_win_rate_lift_pct
    ):
        blockers.append("selection_win_rate_lift_not_positive")

    candidate_groups = [
        group for group in list(candidate_replay.get("candidate_groups") or []) if isinstance(group, dict)
    ]
    if not candidate_groups:
        blockers.append("candidate_groups_missing")
    if any(group.get("candidate_kind") == "ticker_specific" for group in candidate_groups):
        blockers.append("ticker_specific_group_present")

    policy = _shadow_policy(candidate_groups)
    if not policy["selection_rule"]["features"]:
        blockers.append("shadow_policy_rule_empty")

    lineage_alignment = _dict((evidence_lineage or {}).get("freshness_alignment"))
    if lineage_alignment.get("verdict") == "tagged_ahead_of_replay":
        warnings.append("prospective_tags_still_ahead_of_phantom_replay")

    driver_quality_verdict = (driver_quality or {}).get("verdict")
    if driver_quality and driver_quality_verdict != "reusable_driver_quality_candidate":
        warnings.append("driver_quality_not_clean_enough_for_generation_code_change")

    evidence_class = "phantom_selectivity"
    warnings.append("phantom_selectivity_is_not_closed_trade_promotion_evidence")

    shadow_ready = not blockers
    verdict = "shadow_policy_preflight_ready" if shadow_ready else "promotion_preflight_blocked"
    return {
        "schema_version": "phantom-selectivity-promotion-preflight-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "gates": gates.payload(),
        "input": {
            "source_artifacts": source_artifacts or {},
            "candidate_replay_verdict": candidate_replay.get("verdict"),
            "lineage_verdict": lineage_alignment.get("verdict"),
            "driver_quality_verdict": driver_quality_verdict,
            "evidence_class": evidence_class,
        },
        "candidate_replay_summary": {
            "candidate_group_count": candidate_replay.get("candidate_group_count"),
            "selection": selection,
            "selection_win_rate_lift_pct": union.get("selection_win_rate_lift_pct"),
            "concentration": union.get("concentration"),
            "promotion_blockers": union.get("promotion_blockers") or [],
        },
        "proposed_shadow_policy": policy,
        "decision": {
            "shadow_or_paper": "go" if shadow_ready else "stop",
            "live_behavior_change": "stop",
            "tuning_config_change": "stop",
            "broker_or_order_change": "stop",
        },
        "required_next_gates": [
            "operator approval before any shadow or paper policy persistence",
            "tag candidate-specific paper/shadow outcomes separately from live behavior",
            "replay or paper results must produce closed trade win/loss/flat evidence before live promotion",
            "driver quality must reach reusable_driver_quality_candidate before generation-code threshold changes",
        ],
        "read_only_scope": {
            "changed_tuning_config": False,
            "changed_broker_settings": False,
            "changed_orders": False,
            "changed_scheduler_state": False,
        },
    }


def _shadow_policy(candidate_groups: list[dict[str, object]]) -> dict[str, object]:
    grouped_values: dict[str, set[str]] = {}
    for group in candidate_groups:
        if group.get("candidate_kind") == "ticker_specific":
            continue
        feature = str(group.get("feature") or "").strip()
        value = str(group.get("value") or "").strip()
        if not feature or not value:
            continue
        grouped_values.setdefault(feature, set()).add(value)
    features = [
        {
            "feature": feature,
            "values": sorted(values),
        }
        for feature, values in sorted(grouped_values.items())
    ]
    return {
        "name": "phantom_selectivity_volatility_bucket_union_shadow",
        "mode": "shadow_or_paper_only",
        "evidence_profile": "phantom_selectivity",
        "selection_rule": {
            "features": features,
            "operator": "or_across_values",
        },
        "behavior_change": {
            "live_orders": False,
            "live_plan_generation_thresholds": False,
            "allowed_effect": "tag_or_paper_track candidate rows matching the rule",
        },
    }


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
