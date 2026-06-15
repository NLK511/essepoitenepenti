from scripts.report_steering_dry_run_quality import (
    SteeringDecisionRow,
    build_report,
    protective_evidence_label,
    suspicious_reasons,
)


def _row(**overrides):
    values = dict(
        id=1,
        broker_account_id="alpaca-paper-default",
        ticker="AAPL",
        decision="keep_position_exits",
        execution_status="dry_run",
        execute_allowed=False,
        reason_codes=[],
        diagnostics={},
        risk_delta={},
        current_price=100.0,
        current_stop_loss=95.0,
        current_take_profit=110.0,
        proposed_stop_loss=None,
        proposed_take_profit=None,
        error_message="",
        created_at="2026-06-01T12:00:00+00:00",
    )
    values.update(overrides)
    return SteeringDecisionRow(**values)


def test_report_counts_thresholds_amendments_and_close_now() -> None:
    rows = [
        _row(id=1, decision="keep_position_exits"),
        _row(id=2, decision="move_stop_to_breakeven_or_profit", proposed_stop_loss=101.0),
        _row(id=3, decision="close_position_now", reason_codes=["confidence_below_threshold"]),
    ]

    report = build_report(rows, sample_size=10, seed=1)

    assert report["totals"]["dry_run_decisions"] == 3
    assert report["totals"]["dry_run_amendments"] == 1
    assert report["totals"]["dry_run_close_now"] == 1
    assert report["by_decision"]["move_stop_to_breakeven_or_profit"] == 1
    assert not report["thresholds"]["dry_run_decisions"]["met"]


def test_suspicious_reasons_flag_missing_and_risk_increasing_evidence() -> None:
    row = _row(
        decision="move_stop_to_breakeven_or_profit",
        current_price=None,
        proposed_stop_loss=None,
        proposed_take_profit=None,
        reason_codes=["missing_price_context"],
        risk_delta={"risk_delta_usd": 12.5},
    )

    reasons = suspicious_reasons(row)

    assert "missing_current_price" in reasons
    assert "amendment_without_proposed_level" in reasons
    assert "missing_evidence_reason" in reasons
    assert "risk_increasing_delta" in reasons


def test_report_collects_recent_samples_and_suspicious_counts() -> None:
    rows = [
        _row(id=1, decision="close_position_now", current_price=None, reason_codes=[]),
        _row(id=2, decision="keep_position_exits"),
    ]

    report = build_report(rows, sample_size=1, seed=1)

    assert report["samples"]["recent"][0]["id"] == 2
    assert report["samples"]["close_now_recent"][0]["id"] == 1
    assert report["suspicious_reason_counts"]["missing_current_price"] == 1
    assert report["suspicious_reason_counts"]["close_now_without_reason_codes"] == 1


def test_report_distinguishes_protective_order_evidence() -> None:
    protected = _row(diagnostics={"has_open_position": True, "linked_exit_orders_missing": False})
    missing = _row(diagnostics={"has_open_position": True, "linked_exit_orders_missing": True})

    report = build_report([protected, missing], sample_size=2, seed=1)

    assert protective_evidence_label(protected) == "protective_orders_present"
    assert protective_evidence_label(missing) == "missing_active_protective_orders"
    assert report["protective_evidence_counts"] == {
        "protective_orders_present": 1,
        "missing_active_protective_orders": 1,
    }
    assert "missing_active_protective_orders" in suspicious_reasons(missing)


def test_suspicious_reasons_flag_expired_open_plan() -> None:
    row = _row(
        decision="move_stop_to_breakeven_or_profit",
        proposed_stop_loss=101.0,
        diagnostics={
            "has_open_position": True,
            "linked_exit_orders_missing": False,
            "expiration_at": "2026-06-01T12:00:00+00:00",
            "now": "2026-06-08T12:00:00+00:00",
        },
    )

    assert "expired_plan_still_open" in suspicious_reasons(row)
