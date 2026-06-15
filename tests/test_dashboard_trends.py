from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.persistence.models import Base
from trade_proposer_app.services.dashboard_trends import DashboardTrendService


@dataclass
class _FakeSummary:
    closed_positions: int
    wins: int
    losses: int
    realized_pnl: float
    average_return_percent: float | None
    simulation_average_return_percent: float | None = None
    win_rate_percent: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "closed_positions": self.closed_positions,
            "resolved_outcomes": self.closed_positions,
            "wins": self.wins,
            "losses": self.losses,
            "realized_pnl": self.realized_pnl,
            "average_return_percent": self.average_return_percent,
            "simulation_average_return_percent": self.simulation_average_return_percent,
            "win_rate_percent": self.win_rate_percent,
        }


class _FakePlan:
    def __init__(self, social_item_count: int) -> None:
        self.signal_breakdown = {"social_item_count": social_item_count}


class _FakePlanRepository:
    def count_plans(self, **kwargs) -> int:
        if kwargs.get("shortlisted"):
            return 2
        action = kwargs.get("action")
        if action in {"long", "short"}:
            return 3
        return 6

    def list_plans(self, **kwargs) -> list[_FakePlan]:
        return [_FakePlan(4), _FakePlan(1)]


class _FakeOutcomeRepository:
    def summarize_actionability_diagnostics(self, **kwargs) -> dict[str, float | int | None]:
        return {
            "actionability_gap_percent": 8.0,
            "actionable_win_rate_percent": 54.0,
            "phantom_win_rate_percent": 62.0,
            "actionable_resolved_outcomes": 10,
            "phantom_resolved_outcomes": 4,
            "actionable_win_outcomes": 5,
            "actionable_loss_outcomes": 5,
            "phantom_win_outcomes": 2,
            "phantom_loss_outcomes": 2,
            "no_action_outcomes": 1,
            "watchlist_outcomes": 1,
        }


class _FakePerformanceMetrics:
    def summarize_broker_closed_positions(self, **kwargs) -> _FakeSummary:
        return _FakeSummary(
            closed_positions=3,
            wins=2,
            losses=1,
            realized_pnl=125.5,
            average_return_percent=3.25,
            win_rate_percent=66.7,
        )

    def summarize_effective_outcomes(self, **kwargs) -> _FakeSummary:
        return _FakeSummary(
            closed_positions=5,
            wins=3,
            losses=2,
            realized_pnl=432.1,
            average_return_percent=7.75,
            simulation_average_return_percent=1.5,
            win_rate_percent=60.0,
        )


class DashboardTrendServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(bind=self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_compute_daily_snapshot_keeps_absolute_and_relative_profit_separate(self) -> None:
        service = DashboardTrendService(self.session)
        service.plan_repository = _FakePlanRepository()
        service.outcome_repository = _FakeOutcomeRepository()
        service.performance_metrics = _FakePerformanceMetrics()
        service._count_ticker_signals = lambda **kwargs: 7
        service._count_records = lambda *args, **kwargs: 8
        service._sum_plan_item_count = lambda plans, key: 9

        snapshot = service._compute_daily_snapshot(date(2026, 5, 2))
        summary = snapshot["dashboard_summary"]
        technical = snapshot["technical_summary"]

        self.assertEqual(summary["total_profit"], 432.1)
        self.assertEqual(summary["average_profit_percent"], 7.75)
        self.assertEqual(summary["profit_percent"], 7.75)
        self.assertNotEqual(summary["total_profit"], summary["profit_percent"])
        self.assertEqual(summary["broker_realized_pnl"], 125.5)
        self.assertEqual(summary["broker_average_profit_percent"], 3.25)
        self.assertEqual(summary["simulated_average_profit_percent"], 1.5)
        self.assertEqual(technical["broker_realized_pnl"], 125.5)

    def test_build_cached_window_metrics_aggregates_daily_snapshots_plus_today(self) -> None:
        service = DashboardTrendService(self.session)
        old_day = date(2026, 5, 1)
        today = date(2026, 5, 2)
        snapshots = {
            old_day: {
                "snapshot_date": old_day.isoformat(),
                "computed_at": datetime(2026, 5, 2, 0, 0, tzinfo=UTC).isoformat(),
                "dashboard_summary": {
                    "plan_amount": 10,
                    "signals_amount": 20,
                    "shortlisted_plans": 5,
                    "actionable_plans": 4,
                    "effective_closed_positions": 4,
                    "effective_wins": 3,
                    "effective_losses": 1,
                    "total_profit": 100.0,
                    "average_profit_percent": 2.0,
                    "broker_closed_positions": 2,
                    "broker_wins": 1,
                    "broker_realized_pnl": 30.0,
                    "broker_average_profit_percent": 1.5,
                },
                "technical_summary": {"news_processed": 7, "bars_stored": 9, "orders_placed": 1},
            }
        }
        today_snapshot = {
            "snapshot_date": today.isoformat(),
            "computed_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC).isoformat(),
            "dashboard_summary": {
                "plan_amount": 5,
                "signals_amount": 10,
                "shortlisted_plans": 2,
                "actionable_plans": 1,
                "effective_closed_positions": 1,
                "effective_wins": 0,
                "effective_losses": 1,
                "total_profit": -10.0,
                "average_profit_percent": -1.0,
                "broker_closed_positions": 1,
                "broker_wins": 1,
                "broker_realized_pnl": 12.0,
                "broker_average_profit_percent": 2.0,
            },
            "technical_summary": {"news_processed": 3, "bars_stored": 4, "orders_placed": 2},
        }
        service._ensure_daily_snapshot = lambda snapshot_date: snapshots[snapshot_date]
        service._compute_partial_day_snapshot = lambda snapshot_date, now: today_snapshot

        payload = service.build_cached_window_metrics(
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC), days=2
        )

        self.assertEqual(
            payload["dashboard_summary"]["aggregate_source"], "daily_snapshots_plus_today"
        )
        self.assertEqual(payload["dashboard_summary"]["plan_amount"], 15)
        self.assertEqual(payload["dashboard_summary"]["shortlist_rate_percent"], 50.0)
        self.assertEqual(payload["dashboard_summary"]["overall_win_rate_percent"], 60.0)
        self.assertEqual(payload["dashboard_summary"]["total_profit"], 90.0)
        self.assertEqual(payload["dashboard_summary"]["average_profit_percent"], 1.4)
        self.assertEqual(payload["technical_summary"]["news_processed"], 10)
        self.assertEqual(payload["technical_summary"]["orders_placed"], 3)

    def test_build_trends_keeps_total_profit_and_average_profit_series_distinct(self) -> None:
        service = DashboardTrendService(self.session)
        day_1 = date(2026, 5, 1)
        day_2 = date(2026, 5, 2)
        snapshots = {
            day_1: {
                "snapshot_date": day_1.isoformat(),
                "computed_at": datetime(2026, 5, 2, 0, 0, tzinfo=UTC).isoformat(),
                "dashboard_summary": {"total_profit": 100.0, "average_profit_percent": 2.5},
                "technical_summary": {"news_processed": 1},
            },
            day_2: {
                "snapshot_date": day_2.isoformat(),
                "computed_at": datetime(2026, 5, 3, 0, 0, tzinfo=UTC).isoformat(),
                "dashboard_summary": {"total_profit": 80.0, "average_profit_percent": 1.5},
                "technical_summary": {"news_processed": 2},
            },
        }
        service._ensure_daily_snapshot = lambda snapshot_date: snapshots[snapshot_date]

        payload = service.build_trends(now=datetime(2026, 5, 3, 12, 0, tzinfo=UTC), days=2)
        total_profit_series = next(
            series for series in payload["series"] if series["key"] == "total_profit"
        )
        average_profit_series = next(
            series for series in payload["series"] if series["key"] == "average_profit_percent"
        )

        self.assertEqual(
            [window["key"] for window in payload["windows"]], [day_1.isoformat(), day_2.isoformat()]
        )
        self.assertEqual(total_profit_series["values"], [100.0, 80.0])
        self.assertEqual(average_profit_series["values"], [2.5, 1.5])
