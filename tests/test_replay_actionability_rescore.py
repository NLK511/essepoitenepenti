from __future__ import annotations

from datetime import datetime, timezone

from trade_proposer_app.services.actionability_floor_calibration import (
    ActionabilityFloorCalibrationService,
    ReplayActionabilityPlanRow,
)
from trade_proposer_app.services.outcome_population import summarize_outcome_population


def _row(*, confidence: float, action: str, outcome: str, reason: str = "below_calibrated_action_threshold") -> ReplayActionabilityPlanRow:
    return ReplayActionabilityPlanRow(
        as_of=datetime(2026, 6, 1, 23, 59, 59, tzinfo=timezone.utc),
        ticker="AAPL",
        action=action,
        confidence_percent=confidence,
        entry_price_low=100.0,
        entry_price_high=100.0,
        stop_loss=97.0,
        take_profit=105.0,
        signal_breakdown={"intended_action": "long"},
        evidence_summary={"action_reason": reason, "setup_family": "continuation"},
        outcome=outcome,
        outcome_status="resolved",
    )


def test_outcome_population_summary_separates_execution_and_phantom_rows() -> None:
    rows = [
        {"outcome": "win", "tier": "tier_a"},
        {"outcome": "phantom_loss", "tier": "tier_b"},
        {"outcome": "phantom_no_entry", "tier": "tier_c"},
    ]

    summary = summarize_outcome_population(
        rows,
        population="replay_tier_a_b",
        outcome_attr="outcome",
        tier_attr="tier",
    )

    assert summary["population"] == "replay_tier_a_b"
    assert summary["row_count"] == 3
    assert summary["resolved_win_loss_count"] == 2
    assert summary["execution_count"] == 1
    assert summary["phantom_count"] == 2
    assert summary["tier_counts"] == {"tier_a": 1, "tier_b": 1, "tier_c": 1}


def test_rescore_promotes_only_threshold_blocked_intended_actions() -> None:
    rows = [
        _row(confidence=51.0, action="no_action", outcome="phantom_win"),
        _row(confidence=54.0, action="no_action", outcome="phantom_loss", reason="context_quality_blocked"),
        _row(confidence=56.0, action="long", outcome="loss"),
    ]

    service = ActionabilityFloorCalibrationService.__new__(ActionabilityFloorCalibrationService)
    summary_50 = service._summarize(rows, 50.0)
    summary_53_75 = service._summarize(rows, 53.75)

    assert summary_50["actionable_count"] == 2
    assert summary_50["wins"] == 1
    assert summary_50["losses"] == 1
    assert summary_50["ev_percent_points"] == 2.0
    assert summary_53_75["actionable_count"] == 1
    assert summary_53_75["wins"] == 0
    assert summary_53_75["losses"] == 1
    assert summary_53_75["ev_percent_points"] == -3.0
