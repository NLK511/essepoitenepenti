from trade_proposer_app.services.plan_policy_evaluator import PlanPolicyEvaluation
from trade_proposer_app.services.plan_reliability_report import PlanReliabilityReport
from trade_proposer_app.services.policy_trust_report import PolicyTrustReportService
from trade_proposer_app.services.trade_policy_evaluation import TradePolicyEvaluationSummary


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


def _policy_review(**overrides):
    return TradePolicyEvaluationSummary(
        policy_evaluation=_evaluation(**overrides),
        reliability_report=PlanReliabilityReport(
            total_outcomes=0,
            resolved_outcomes=0,
            broker_outcomes=0,
            simulation_outcomes=0,
            plan_outcomes=0,
            by_confidence_bucket=[],
            by_setup_family=[],
            by_action=[],
        ),
    )


def test_policy_trust_report_records_missing_required_inputs() -> None:
    report = PolicyTrustReportService(outcomes=None).build(_policy_review())  # type: ignore[arg-type]

    assert report.edge_validation_gate.label != "eligible_for_cautious_expansion"
    assert "walk_forward_input_missing" in report.missing_inputs
    assert "degraded_input_input_missing" in report.missing_inputs
    assert "broker_reconciliation_input_missing" in report.missing_inputs
    assert "baseline_comparison_input_missing" in report.missing_inputs
    assert "drawdown_input_missing" in report.missing_inputs
    assert "loss_streak_input_missing" in report.missing_inputs
    assert "walk_forward_input_missing" in report.edge_validation_gate.reasons
    assert "concentration_input_missing" in report.edge_validation_gate.reasons
    assert "broker_reconciliation_input_missing" in report.edge_validation_gate.reasons


def test_policy_trust_report_can_pass_when_required_inputs_are_supplied() -> None:
    report = PolicyTrustReportService(outcomes=None).build(  # type: ignore[arg-type]
        _policy_review(),
        walk_forward_validation={"qualified_slices": 3, "promotion_recommended": True},
        evidence_concentration={"ready_for_expansion": True},
        degraded_input_summary={"degraded_input_share_percent": 5.0},
        risk_state={"metrics": {"broker_drift_severity": "ok", "broker_snapshot_available": True}, "reasons": []},
        baseline_comparison_summary={"passed": True},
        drawdown_summary={"breached": False},
        loss_streak_summary={"breached": False},
    )

    assert report.missing_inputs == []
    assert report.edge_validation_gate.label == "eligible_for_cautious_expansion"
    assert report.policy_health_headline.label == "healthy"


def test_policy_trust_headline_cannot_contradict_blocked_gate() -> None:
    report = PolicyTrustReportService(outcomes=None).build(  # type: ignore[arg-type]
        _policy_review(),
        walk_forward_validation={"qualified_slices": 3, "promotion_recommended": True},
        evidence_concentration={"ready_for_expansion": True},
        degraded_input_summary={"degraded_input_share_percent": 5.0},
        risk_state={"metrics": {"broker_drift_severity": "material", "broker_snapshot_available": True}, "reasons": ["broker_reconciliation_material"]},
        baseline_comparison_summary={"passed": True},
        drawdown_summary={"breached": False},
        loss_streak_summary={"breached": False},
    )

    assert report.edge_validation_gate.label == "demote_or_halt"
    assert report.policy_health_headline.label == "degraded"
    assert "edge_gate_not_expansion_ready" in report.policy_health_headline.reasons
    assert "broker_reconciliation_uncertain" in report.edge_validation_gate.reasons
