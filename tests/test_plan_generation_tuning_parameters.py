from trade_proposer_app.services.plan_generation_tuning_parameters import (
    candidate_validation_depth,
    parameter_definitions,
)


def test_parameter_definitions_expose_validation_depth() -> None:
    parameters = {item["key"]: item for item in parameter_definitions()}

    assert parameters["global.actionable_confidence_floor_percent"]["validation_depth"] == "rescore_only"
    assert parameters["global.entry_band_risk_fraction"]["validation_depth"] == "frozen_input_plan_regeneration"
    assert parameters["setup_family.breakout.stop_distance_multiplier"]["validation_depth"] == "frozen_input_plan_regeneration"


def test_candidate_validation_depth_uses_deepest_changed_key() -> None:
    result = candidate_validation_depth([
        "global.actionable_confidence_floor_percent",
        "setup_family.breakout.stop_distance_multiplier",
    ])

    assert result["validation_depth"] == "frozen_input_plan_regeneration"
    assert result["unknown_keys"] == []
    assert result["parameter_depths"]["global.actionable_confidence_floor_percent"]["validation_depth"] == "rescore_only"


def test_candidate_validation_depth_fails_closed_for_unknown_keys() -> None:
    result = candidate_validation_depth(["signal_gating.shortlist_aggressiveness"])

    assert result["validation_depth"] == "full_orchestration_replay"
    assert result["unknown_keys"] == ["signal_gating.shortlist_aggressiveness"]
