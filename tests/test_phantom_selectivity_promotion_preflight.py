from __future__ import annotations

from trade_proposer_app.services.phantom_selectivity_promotion_preflight import (
    build_phantom_selectivity_promotion_preflight,
)


def _candidate_replay(*, ready: bool = True) -> dict[str, object]:
    return {
        "verdict": "promotion_candidate_ready" if ready else "research_candidate_only",
        "promotion_candidate_ready": ready,
        "candidate_group_count": 2,
        "candidate_groups": [
            {
                "candidate_kind": "reusable_feature",
                "feature": "volatility_bucket",
                "value": "40-50",
            },
            {
                "candidate_kind": "reusable_feature",
                "feature": "volatility_bucket",
                "value": "80-90",
            },
        ],
        "combined_union": {
            "promotion_ready": ready,
            "promotion_blockers": [] if ready else ["selection_rows_below_promotion_minimum"],
            "selection": {
                "count": 111 if ready else 80,
                "distinct_date_count": 23,
                "expected_value_per_observation": 0.41054,
                "win_rate_percent": 45.9459,
            },
            "selection_win_rate_lift_pct": 7.4042,
            "concentration": {
                "ticker": {"top_share_percent": 9.9099, "top_value": "hpe"},
            },
        },
    }


def test_preflight_allows_shadow_policy_but_blocks_live_behavior_change() -> None:
    report = build_phantom_selectivity_promotion_preflight(
        candidate_replay=_candidate_replay(),
        evidence_lineage={
            "freshness_alignment": {
                "verdict": "tagged_ahead_of_replay",
            }
        },
        driver_quality={
            "verdict": "analysis_only_driver_leads",
        },
    )

    assert report["verdict"] == "shadow_policy_preflight_ready"
    assert report["decision"]["shadow_or_paper"] == "go"
    assert report["decision"]["live_behavior_change"] == "stop"
    assert report["decision"]["tuning_config_change"] == "stop"
    assert report["proposed_shadow_policy"]["selection_rule"]["features"] == [
        {"feature": "volatility_bucket", "values": ["40-50", "80-90"]}
    ]
    assert "phantom_selectivity_is_not_closed_trade_promotion_evidence" in report["warnings"]
    assert "driver_quality_not_clean_enough_for_generation_code_change" in report["warnings"]


def test_preflight_blocks_when_candidate_replay_is_not_ready() -> None:
    report = build_phantom_selectivity_promotion_preflight(
        candidate_replay=_candidate_replay(ready=False),
    )

    assert report["verdict"] == "promotion_preflight_blocked"
    assert report["decision"]["shadow_or_paper"] == "stop"
    assert "candidate_replay_not_promotion_ready" in report["blockers"]
    assert "combined_union:selection_rows_below_promotion_minimum" in report["blockers"]
