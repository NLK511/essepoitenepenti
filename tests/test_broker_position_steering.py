from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.services.broker_position_steering import (
    BrokerSteeringConfig,
    BrokerSteeringEngine,
    BrokerSteeringState,
)


NOW = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)


def _config(**overrides) -> BrokerSteeringConfig:
    return BrokerSteeringConfig(enabled=True, dry_run=False, **overrides)


def _state(**overrides) -> BrokerSteeringState:
    data = {
        "recommendation_plan_id": 17,
        "ticker": "AAPL",
        "direction": "long",
        "current_price": 100.0,
        "entry_price": 100.0,
        "original_stop_loss": 95.0,
        "original_take_profit": 110.0,
        "current_stop_loss": 95.0,
        "current_take_profit": 110.0,
        "confidence_percent": 70.0,
        "calibrated_confidence_percent": None,
        "actionability": "long",
        "analysis_direction": "long",
        "severe_negative_news": False,
        "price_chase_percent": None,
        "volatility_percent": None,
        "has_pending_order": False,
        "has_open_position": False,
        "broker_ownership_known": True,
        "broker_reconciliation_healthy": True,
        "broker_reconciliation_age_minutes": 0.0,
        "linked_exit_orders_missing": False,
        "expiration_at": None,
        "now": NOW,
    }
    data.update(overrides)
    return BrokerSteeringState(**data)


def test_pending_expired_order_cancels() -> None:
    engine = BrokerSteeringEngine()
    state = _state(has_pending_order=True, has_open_position=False, expiration_at=NOW - timedelta(minutes=6))

    decision = engine.evaluate(state, _config())

    assert decision.decision == "cancel_pending_order"
    assert "pending_expired" in decision.reason_codes
    assert decision.execute_allowed is True


def test_pending_order_with_only_missing_news_is_kept() -> None:
    engine = BrokerSteeringEngine()
    state = _state(has_pending_order=True, has_open_position=False, severe_negative_news=False, confidence_percent=70.0, actionability="long")

    decision = engine.evaluate(state, _config())

    assert decision.decision == "keep_pending_order"
    assert "insufficient_invalidation_evidence" in decision.reason_codes


def test_pending_order_with_two_strong_invalidation_signals_cancels() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        has_pending_order=True,
        has_open_position=False,
        confidence_percent=54.0,
        actionability="no_action",
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "cancel_pending_order"
    assert "pending_confidence_below_threshold" in decision.reason_codes
    assert "pending_actionability_no_action" in decision.reason_codes


def test_long_stop_never_moves_down() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        has_pending_order=False,
        has_open_position=True,
        current_price=101.0,
        entry_price=100.0,
        current_stop_loss=96.0,
        original_stop_loss=95.0,
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "move_stop_to_breakeven_or_profit"
    assert round(decision.proposed_stop_loss or 0.0, 4) == 100.1
    assert (decision.proposed_stop_loss or 0.0) > 96.0


def test_short_stop_never_moves_up() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        direction="short",
        actionability="short",
        analysis_direction="short",
        current_price=98.0,
        entry_price=100.0,
        current_stop_loss=105.0,
        original_stop_loss=106.0,
        has_open_position=True,
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "move_stop_to_breakeven_or_profit"
    assert round(decision.proposed_stop_loss or 0.0, 4) == 99.9
    assert (decision.proposed_stop_loss or 0.0) < 105.0


def test_severe_long_thesis_invalidation_proposes_close_now() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        has_open_position=True,
        confidence_percent=39.0,
        actionability="no_action",
        analysis_direction="bearish",
        severe_negative_news=True,
        linked_exit_orders_missing=False,
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "close_position_now"
    assert "position_confidence_below_close_threshold" in decision.reason_codes
    assert "position_actionability_no_action" in decision.reason_codes
    assert "position_analysis_conflict" in decision.reason_codes


def test_deteriorating_profitable_long_tightens_stop() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        has_open_position=True,
        current_price=100.2,
        current_stop_loss=99.7,
        original_stop_loss=95.0,
        confidence_percent=49.0,
        analysis_direction="bearish",
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "tighten_stop_loss"
    assert round(decision.proposed_stop_loss or 0.0, 4) == 99.8493
    assert "position_confidence_below_hold_threshold" in decision.reason_codes


def test_deteriorating_profitable_long_lowers_take_profit_when_stop_is_already_tight_enough() -> None:
    engine = BrokerSteeringEngine()
    state = _state(
        has_open_position=True,
        current_price=100.2,
        current_stop_loss=100.0,
        original_stop_loss=99.9,
        current_take_profit=110.0,
        confidence_percent=49.0,
        analysis_direction="bearish",
    )

    decision = engine.evaluate(state, _config())

    assert decision.decision == "lower_take_profit"
    assert round(decision.proposed_take_profit or 0.0, 3) == 100.701
    assert (decision.proposed_take_profit or 0.0) < 110.0
    assert (decision.proposed_take_profit or 0.0) > 100.2


def test_broker_uncertainty_produces_manual_review() -> None:
    engine = BrokerSteeringEngine()
    state = _state(has_open_position=True, broker_ownership_known=False)

    decision = engine.evaluate(state, _config())

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True
    assert "broker_uncertainty" in decision.reason_codes


def test_missing_protective_child_evidence_blocks_mutation() -> None:
    engine = BrokerSteeringEngine()
    state = _state(has_open_position=True, linked_exit_orders_missing=True)

    decision = engine.evaluate(state, _config())

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True
    assert "position_linked_exit_orders_missing" in decision.reason_codes


def test_missing_reconciliation_age_blocks_mutation() -> None:
    engine = BrokerSteeringEngine()
    state = _state(has_open_position=True, broker_reconciliation_age_minutes=None)

    decision = engine.evaluate(state, _config())

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True
    assert "broker_reconciliation_stale" in decision.reason_codes


def test_unknown_direction_produces_manual_review() -> None:
    engine = BrokerSteeringEngine()
    state = _state(direction="unknown", actionability="no_action", analysis_direction=None, has_open_position=True)

    decision = engine.evaluate(state, _config())

    assert decision.decision == "manual_review_required"
    assert decision.requires_manual_review is True
    assert "ambiguous_direction" in decision.reason_codes
