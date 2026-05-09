from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.services.plan_resolution_engine import PlanResolutionConfig, PlanResolutionEngine


def _plan(**overrides) -> RecommendationPlan:
    data = {
        "id": 1,
        "ticker": "AAPL",
        "horizon": "1w",
        "action": "long",
        "confidence_percent": 70.0,
        "entry_price_low": 100.0,
        "entry_price_high": 101.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "holding_period_days": 5,
        "risk_reward_ratio": 2.0,
        "thesis_summary": "test",
        "computed_at": datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc),
        "signal_breakdown": {"setup_family": "continuation"},
    }
    data.update(overrides)
    return RecommendationPlan(**data)


def _frame(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    index = [pd.Timestamp(ts) for ts, _high, _low, _close in rows]
    return pd.DataFrame(
        {
            "High": [high for _ts, high, _low, _close in rows],
            "Low": [low for _ts, _high, low, _close in rows],
            "Close": [close for _ts, _high, _low, close in rows],
        },
        index=index,
    )


def test_plan_resolution_engine_resolves_take_before_stop() -> None:
    engine = PlanResolutionEngine(PlanResolutionConfig())
    outcome = engine.evaluate_plan(
        _plan(),
        _frame([
            ("2026-05-01T14:01:00Z", 101.0, 100.0, 100.5),
            ("2026-05-01T14:02:00Z", 111.0, 100.0, 110.5),
        ]),
        run_id=7,
    )

    assert outcome.outcome == "win"
    assert outcome.status == "resolved"
    assert outcome.entry_touched is True
    assert outcome.take_profit_hit is True
    assert outcome.stop_loss_hit is False


def test_plan_resolution_engine_marks_near_entry_miss_without_relabeling_as_win() -> None:
    engine = PlanResolutionEngine(PlanResolutionConfig(near_entry_miss_threshold_percent=0.25))
    outcome = engine.evaluate_plan(
        _plan(),
        _frame([
            ("2026-05-01T14:01:00Z", 99.8, 98.5, 99.5),
            ("2026-05-01T14:02:00Z", 109.0, 102.0, 108.0),
        ]),
        run_id=7,
    )

    assert outcome.outcome == "no_entry"
    assert outcome.status == "open"
    assert outcome.near_entry_miss is True
    assert outcome.direction_worked_without_entry is True


def test_plan_resolution_engine_resolves_phantom_trade_outcomes() -> None:
    engine = PlanResolutionEngine(PlanResolutionConfig())
    plan = _plan(action="no_action", signal_breakdown={"setup_family": "continuation", "intended_action": "long"})
    outcome = engine.evaluate_plan(
        plan,
        _frame([
            ("2026-05-01T14:01:00Z", 101.0, 100.0, 100.5),
            ("2026-05-01T14:02:00Z", 111.0, 100.0, 110.5),
        ]),
        intended_action="long",
        run_id=7,
    )

    assert outcome.outcome == "phantom_win"
    assert outcome.status == "resolved"
