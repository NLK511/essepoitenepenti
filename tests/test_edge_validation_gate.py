from trade_proposer_app.services.edge_validation_gate import EdgeValidationGateService
from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation


def _evaluation(**overrides):
    values = {
        "policy_id": "test",
        "total_outcomes": 250,
        "selected_outcomes": 120,
        "resolved_selected_outcomes": 110,
        "broker_selected_outcomes": 70,
        "simulation_selected_outcomes": 50,
        "win_count": 62,
        "loss_count": 48,
        "win_rate_percent": 56.4,
        "average_confidence_percent": 58.0,
        "calibration_gap_percent": 1.6,
        "realized_pnl": 250.0,
        "average_return_percent": 1.2,
        "average_r_multiple": 0.18,
        "profit_factor": 1.35,
        "calibration_penalty": 1.6,
        "robustness_label": "stable",
        "selection_rate_percent": 48.0,
    }
    values.update(overrides)
    return PlanPolicyEvaluation(**values)


def test_edge_validation_gate_allows_cautious_expansion_when_thresholds_pass() -> None:
    report = EdgeValidationGateService().evaluate(
        _evaluation(),
        walk_forward_validation={"qualified_slices": 3, "promotion_recommended": True},
    )

    assert report.label == "eligible_for_cautious_expansion"
    assert report.reasons == []
    assert report.broker_outcome_share_percent == 58.3


def test_edge_validation_gate_blocks_thin_simulation_heavy_evidence() -> None:
    report = EdgeValidationGateService().evaluate(
        _evaluation(resolved_selected_outcomes=12, broker_selected_outcomes=2, selected_outcomes=20),
        walk_forward_validation={"qualified_slices": 1, "promotion_recommended": False},
    )

    assert report.label == "research_only"
    assert "thin_selected_sample" in report.reasons
    assert "thin_broker_sample" in report.reasons
    assert "simulation_heavy_evidence" in report.reasons
    assert "walk_forward_not_recommended" in report.reasons


def test_edge_validation_gate_demotes_when_broker_reconciliation_is_uncertain() -> None:
    report = EdgeValidationGateService().evaluate(
        _evaluation(),
        walk_forward_validation={"qualified_slices": 3, "promotion_recommended": True},
        broker_reconciliation_uncertain=True,
    )

    assert report.label == "demote_or_halt"
    assert "broker_reconciliation_uncertain" in report.reasons
