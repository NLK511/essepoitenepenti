from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import Mock

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService, _CheapScanCandidate


COMPUTED_AT = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def _service(*, confidence_threshold: float = 60.0, plan_generation_tuning_config: dict[str, float] | None = None) -> WatchlistOrchestrationService:
    return WatchlistOrchestrationService(
        context_snapshots=Mock(),
        recommendation_plans=Mock(),
        cheap_scan_service=Mock(),
        deep_analysis_service=Mock(),
        confidence_threshold=confidence_threshold,
        plan_generation_tuning_config=plan_generation_tuning_config,
    )


def _watchlist(*, allow_shorts: bool = True) -> Watchlist:
    return Watchlist(
        id=7,
        name="parity-watchlist",
        default_horizon=StrategyHorizon.ONE_WEEK,
        allow_shorts=allow_shorts,
    )


def _candidate(*, direction: str = "long", confidence: float = 55.0) -> _CheapScanCandidate:
    return _CheapScanCandidate(
        "AAPL",
        direction,
        confidence,
        88.0,
        ["cheap warning"],
        "cheap scan bullish",
    )


def _signal(
    *,
    direction: str = "long",
    confidence: float = 55.0,
    warnings: list[str] | None = None,
    shortlisted: bool = True,
    shortlist_rank: int | None = 2,
) -> TickerSignalSnapshot:
    return TickerSignalSnapshot(
        id=11,
        ticker="AAPL",
        horizon=StrategyHorizon.ONE_WEEK,
        direction=direction,
        confidence_percent=confidence,
        attention_score=88.0,
        warnings=warnings if warnings is not None else ["signal warning"],
        diagnostics={"shortlisted": shortlisted, "shortlist_rank": shortlist_rank, "mode": "deep_analysis"},
        source_breakdown={"cheap_scan_summary": "cheap summary"},
        computed_at=COMPUTED_AT,
    )


def _deep_output(
    *,
    direction: RecommendationDirection = RecommendationDirection.LONG,
    confidence: float = 74.0,
    setup_family: str = "breakout",
    context_bias: str = "tailwind",
    extra_transmission: dict[str, object] | None = None,
) -> RunOutput:
    transmission: dict[str, object] = {
        "context_bias": context_bias,
        "alignment_percent": 70.0,
        "expected_transmission_window": "2d_5d",
        "primary_drivers": ["semiconductor_ai_demand_strength"],
        "primary_driver_details": [{"key": "semiconductor_ai_demand_strength", "label": "AI demand strength"}],
        "matched_ticker_relationships": [
            {
                "type": "supplier_to",
                "type_label": "supplier to",
                "target": "TSM",
                "target_label": "TSM",
                "channel": "supply_chain",
                "channel_label": "supply chain",
            }
        ],
        "conflict_flags": [],
    }
    if extra_transmission:
        transmission.update(extra_transmission)
    return RunOutput(
        recommendation=Recommendation(
            ticker="AAPL",
            direction=direction,
            confidence=confidence,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=112.0,
        ),
        diagnostics=RunDiagnostics(
            analysis_json=json.dumps(
                {
                    "summary": {"text": "Deep summary"},
                    "ticker_deep_analysis": {
                        "setup_family": setup_family,
                        "confidence_components": {
                            "context_confidence": 66.0,
                            "directional_confidence": confidence,
                            "catalyst_confidence": 68.0,
                            "technical_clarity": 71.0,
                            "execution_clarity": 73.0,
                            "data_quality_cap": 92.0,
                        },
                        "transmission_analysis": transmission,
                    },
                }
            )
        ),
    )


def _plan_contract(plan) -> dict[str, object]:
    return {
        "ticker": plan.ticker,
        "horizon": plan.horizon.value if hasattr(plan.horizon, "value") else plan.horizon,
        "action": plan.action,
        "status": plan.status,
        "confidence_percent": plan.confidence_percent,
        "entry_price_low": plan.entry_price_low,
        "entry_price_high": plan.entry_price_high,
        "stop_loss": plan.stop_loss,
        "take_profit": plan.take_profit,
        "holding_period_days": plan.holding_period_days,
        "risk_reward_ratio": plan.risk_reward_ratio,
        "thesis_summary": plan.thesis_summary,
        "rationale_summary": plan.rationale_summary,
        "warnings": plan.warnings,
        "risks": plan.risks,
        "evidence": {
            "setup_family": plan.evidence_summary.get("setup_family"),
            "action_reason": plan.evidence_summary.get("action_reason"),
            "action_reason_detail": plan.evidence_summary.get("action_reason_detail"),
            "entry_style": plan.evidence_summary.get("entry_style"),
            "stop_style": plan.evidence_summary.get("stop_style"),
            "target_style": plan.evidence_summary.get("target_style"),
            "timing_expectation": plan.evidence_summary.get("timing_expectation"),
            "evaluation_focus": plan.evidence_summary.get("evaluation_focus"),
            "invalidation_summary": plan.evidence_summary.get("invalidation_summary"),
        },
        "signal": {
            "shortlisted": plan.signal_breakdown.get("shortlisted"),
            "shortlist_rank": plan.signal_breakdown.get("shortlist_rank"),
            "intended_action": plan.signal_breakdown.get("intended_action"),
            "cheap_scan_confidence_percent": plan.signal_breakdown.get("cheap_scan_confidence_percent"),
            "deep_analysis_confidence_percent": plan.signal_breakdown.get("deep_analysis_confidence_percent"),
            "raw_plan_confidence_percent": plan.signal_breakdown.get("raw_plan_confidence_percent"),
            "calibrated_confidence_percent": plan.signal_breakdown.get("calibrated_confidence_percent"),
            "transmission_bias": plan.signal_breakdown.get("transmission_summary", {}).get("transmission_bias"),
            "expected_transmission_window": plan.signal_breakdown.get("transmission_summary", {}).get("expected_transmission_window"),
            "primary_drivers": plan.signal_breakdown.get("transmission_summary", {}).get("primary_drivers"),
            "matched_ticker_relationships": plan.signal_breakdown.get("transmission_summary", {}).get("matched_ticker_relationships"),
        },
    }


def test_actionable_plan_framing_payload_contract_is_stable() -> None:
    service = _service()

    plan = service._build_plan_from_signal(
        _watchlist(),
        _candidate(),
        _signal(),
        deep_output=_deep_output(),
        deep_error=None,
        calibration_summary=None,
        job_id=101,
        run_id=202,
    )

    assert _plan_contract(plan) == {
        "ticker": "AAPL",
        "horizon": "1w",
        "action": "long",
        "status": "partial",
        "confidence_percent": 74.0,
        "entry_price_low": 100.0,
        "entry_price_high": 100.0,
        "stop_loss": 95.75,
        "take_profit": 113.44,
        "holding_period_days": 5,
        "risk_reward_ratio": 2.4,
        "thesis_summary": "Deep summary",
        "rationale_summary": "cheap scan bullish · setup family breakout · context tailwind · window 2d_5d · driver AI demand strength · relationship supplier to TSM via supply chain · attention 88.0 · confidence 55.0",
        "warnings": ["signal warning"],
        "risks": [
            "signal warning",
            "failed follow-through can reverse quickly after entry",
            "ticker relationship read-through can break if peer, supplier, or customer confirmation fades",
        ],
        "evidence": {
            "setup_family": "breakout",
            "action_reason": "actionable_setup",
            "action_reason_detail": "Promoted because the breakout structure met the current execution and confidence requirements. Relationship read-through: supplier to TSM via supply chain.",
            "entry_style": "break_or_retest",
            "stop_style": "below_break_level_with_buffer",
            "target_style": "measured_move_or_next_resistance",
            "timing_expectation": "2d_5d",
            "evaluation_focus": ["follow_through_speed", "false_break_frequency", "retest_hold_quality"],
            "invalidation_summary": "invalidate if the breakout loses the breakout level or fails its retest; primary driver to monitor is AI demand strength; ticker read-through to monitor is supplier to TSM via supply chain",
        },
        "signal": {
            "shortlisted": True,
            "shortlist_rank": 2,
            "intended_action": "long",
            "cheap_scan_confidence_percent": 55.0,
            "deep_analysis_confidence_percent": 74.0,
            "raw_plan_confidence_percent": 74.0,
            "calibrated_confidence_percent": 74.0,
            "transmission_bias": "tailwind",
            "expected_transmission_window": "2d_5d",
            "primary_drivers": ["semiconductor_ai_demand_strength"],
            "matched_ticker_relationships": [
                {
                    "type": "supplier_to",
                    "type_label": "supplier to",
                    "target": "TSM",
                    "target_label": "TSM",
                    "channel": "supply_chain",
                    "channel_label": "supply chain",
                }
            ],
        },
    }


def test_actionable_short_plan_framing_payload_contract_is_stable() -> None:
    service = _service()

    plan = service._build_plan_from_signal(
        _watchlist(allow_shorts=True),
        _candidate(direction="short"),
        _signal(direction="short"),
        deep_output=_deep_output(direction=RecommendationDirection.SHORT, confidence=74.0, setup_family="breakdown"),
        deep_error=None,
        calibration_summary=None,
        job_id=101,
        run_id=202,
    )

    contract = _plan_contract(plan)
    assert contract["action"] == "short"
    assert contract["status"] == "partial"
    assert contract["confidence_percent"] == 74.0
    assert contract["entry_price_low"] == 100.0
    assert contract["entry_price_high"] == 100.0
    assert contract["stop_loss"] == 104.25
    assert contract["take_profit"] == 86.56
    assert contract["holding_period_days"] == 5
    assert contract["risk_reward_ratio"] == 2.4
    assert contract["rationale_summary"] == "cheap scan bullish · setup family breakdown · context tailwind · window 2d_5d · driver AI demand strength · relationship supplier to TSM via supply chain · attention 88.0 · confidence 55.0"
    assert contract["risks"] == [
        "signal warning",
        "failed follow-through can reverse quickly after entry",
        "ticker relationship read-through can break if peer, supplier, or customer confirmation fades",
        "short squeeze risk remains elevated if sentiment reverses",
    ]
    assert contract["evidence"] == {
        "setup_family": "breakdown",
        "action_reason": "actionable_setup",
        "action_reason_detail": "Promoted because the breakdown structure met the current execution and confidence requirements. Relationship read-through: supplier to TSM via supply chain.",
        "entry_style": "break_or_failed_retest",
        "stop_style": "above_failed_retest_level",
        "target_style": "measured_move_or_next_support",
        "timing_expectation": "2d_5d",
        "evaluation_focus": ["support_failure_persistence", "reclaim_risk", "downside_extension_quality"],
        "invalidation_summary": "invalidate if the breakdown reclaims lost support or the failed retest resolves higher; primary driver to monitor is AI demand strength; ticker read-through to monitor is supplier to TSM via supply chain",
    }
    assert contract["signal"]["intended_action"] == "short"
    assert contract["signal"]["deep_analysis_confidence_percent"] == 74.0


def test_confidence_floor_blocks_actionable_plan_but_preserves_framing() -> None:
    service = _service(confidence_threshold=60.0, plan_generation_tuning_config={"global.actionable_confidence_floor_percent": 80.0})

    plan = service._build_plan_from_signal(
        _watchlist(),
        _candidate(),
        _signal(),
        deep_output=_deep_output(),
        deep_error=None,
        calibration_summary=None,
        job_id=101,
        run_id=202,
    )

    contract = _plan_contract(plan)
    assert contract["action"] == "no_action"
    assert contract["status"] == "partial"
    assert contract["confidence_percent"] == 74.0
    assert contract["entry_price_low"] == 100.0
    assert contract["entry_price_high"] == 100.0
    assert contract["stop_loss"] == 95.75
    assert contract["take_profit"] == 113.44
    assert contract["evidence"]["action_reason"] == "below_calibrated_action_threshold"


def test_no_action_plan_from_policy_gate_preserves_intended_trade_framing_for_phantom_evaluation() -> None:
    service = _service(confidence_threshold=60.0)

    plan = service._build_plan_from_signal(
        _watchlist(allow_shorts=False),
        _candidate(direction="short"),
        _signal(direction="short"),
        deep_output=_deep_output(direction=RecommendationDirection.SHORT, confidence=74.0, setup_family="breakdown"),
        deep_error=None,
        calibration_summary=None,
        job_id=101,
        run_id=202,
    )

    contract = _plan_contract(plan)
    assert contract["action"] == "no_action"
    assert contract["status"] == "partial"
    assert contract["entry_price_low"] == 100.0
    assert contract["entry_price_high"] == 100.0
    assert contract["stop_loss"] == 104.25
    assert contract["take_profit"] == 86.56
    assert contract["holding_period_days"] == 5
    assert contract["risk_reward_ratio"] == 2.4
    assert contract["evidence"]["setup_family"] == "breakdown"
    assert contract["evidence"]["action_reason"] == "shorts_disabled"
    assert contract["signal"]["intended_action"] == "short"
    assert "watchlist does not allow shorts" in contract["warnings"]
    assert contract["thesis_summary"] == "Detected a breakdown candidate, but the watchlist policy does not permit the required short expression. Read-through to watch: supplier to TSM via supply chain."


def test_deep_analysis_unavailable_plan_framing_payload_contract_is_stable() -> None:
    service = _service()

    plan = service._build_plan_from_signal(
        _watchlist(),
        _candidate(),
        _signal(warnings=[]),
        deep_output=None,
        deep_error="provider unavailable",
        calibration_summary=None,
        job_id=101,
        run_id=202,
    )

    contract = _plan_contract(plan)
    assert contract["action"] == "no_action"
    assert contract["status"] == "degraded"
    assert contract["confidence_percent"] == 55.0
    assert contract["entry_price_low"] is None
    assert contract["stop_loss"] is None
    assert contract["take_profit"] is None
    assert contract["thesis_summary"] == "Deep analysis did not complete; no actionable plan emitted."
    assert contract["evidence"]["action_reason"] == "deep_analysis_unavailable"
    assert contract["signal"]["shortlisted"] is True
    assert contract["signal"]["shortlist_rank"] == 2
    assert contract["signal"]["intended_action"] is None
    assert contract["signal"]["deep_analysis_confidence_percent"] is None
    assert contract["signal"]["raw_plan_confidence_percent"] == 55.0


def test_non_shortlisted_no_action_plan_framing_payload_contract_is_stable() -> None:
    service = _service()
    signal = _signal(warnings=[], shortlisted=False, shortlist_rank=None)

    plan = service._build_no_action_plan(
        _watchlist(),
        _candidate(confidence=52.0),
        signal,
        calibration_summary=None,
        job_id=101,
        run_id=202,
        reason="Not shortlisted after cheap scan.",
    )

    contract = _plan_contract(plan)
    assert contract["action"] == "no_action"
    assert contract["status"] == "ok"
    assert contract["confidence_percent"] == 55.0
    assert contract["entry_price_low"] is None
    assert contract["holding_period_days"] is None
    assert contract["thesis_summary"] == "Not shortlisted after cheap scan."
    assert contract["rationale_summary"] == "cheap scan bullish · setup family mean reversion · context headwind · driver attention leader · attention 88.0 · confidence 55.0"
    assert contract["evidence"]["setup_family"] == "mean_reversion"
    assert contract["evidence"]["action_reason"] == "not_shortlisted"
    assert contract["evidence"]["entry_style"] == "reversal_confirmation"
    assert contract["signal"]["shortlisted"] is False
    assert contract["signal"]["shortlist_rank"] is None
    assert contract["signal"]["intended_action"] is None
    assert contract["signal"]["cheap_scan_confidence_percent"] == 55.0
    assert contract["signal"]["deep_analysis_confidence_percent"] is None

