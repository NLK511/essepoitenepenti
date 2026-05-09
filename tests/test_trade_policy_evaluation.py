from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReport
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationSummary


def _evaluation(**overrides) -> PlanPolicyEvaluation:
    data = {
        "policy_id": "active",
        "total_outcomes": 100,
        "selected_outcomes": 40,
        "resolved_selected_outcomes": 25,
        "broker_selected_outcomes": 5,
        "simulation_selected_outcomes": 35,
        "win_count": 13,
        "loss_count": 12,
        "win_rate_percent": 52.0,
        "average_confidence_percent": 60.0,
        "calibration_gap_percent": 8.0,
        "realized_pnl": 10.0,
        "average_return_percent": 1.0,
        "average_r_multiple": 0.1,
        "profit_factor": 1.2,
        "calibration_penalty": 8.0,
        "robustness_label": "usable",
        "selection_rate_percent": 40.0,
    }
    data.update(overrides)
    return PlanPolicyEvaluation(**data)


def _reliability() -> PlanReliabilityReport:
    return PlanReliabilityReport(
        total_outcomes=0,
        resolved_outcomes=0,
        broker_outcomes=0,
        simulation_outcomes=0,
        plan_outcomes=0,
        by_confidence_bucket=[],
        by_setup_family=[],
        by_action=[],
    )


def test_policy_health_is_single_top_level_operator_contract() -> None:
    summary = TradePolicyEvaluationSummary(policy_evaluation=_evaluation(), reliability_report=_reliability())

    payload = summary.to_dict()

    assert payload["policy_health"]["label"] == "watch"
    assert "mostly_simulated_evidence" in payload["policy_health"]["reasons"]
    assert payload["policy_health"]["broker_outcome_share_percent"] == 12.5


def test_policy_health_marks_empty_policy_as_insufficient() -> None:
    summary = TradePolicyEvaluationSummary(
        policy_evaluation=_evaluation(selected_outcomes=0, resolved_selected_outcomes=0, win_rate_percent=None, realized_pnl=0.0),
        reliability_report=_reliability(),
    )

    assert summary.policy_health.label == "insufficient"
    assert "thin_resolved_sample" in summary.policy_health.reasons
