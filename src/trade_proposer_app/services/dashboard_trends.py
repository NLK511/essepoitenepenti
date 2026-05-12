from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    BrokerOrderExecutionRecord,
    HistoricalMarketBarRecord,
    HistoricalNewsRecord,
    TickerSignalSnapshotRecord,
)
from trade_proposer_app.repositories.dashboard_trends import DashboardTrendRepository
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.trading_performance_metrics import TradingPerformanceMetricsService


TREND_SERIES: list[tuple[str, str, str]] = [
    ("overall_win_rate_percent", "Overall win rate", "percent"),
    ("total_profit", "Total profit", "currency"),
    ("average_profit_percent", "Avg profit", "percent"),
    ("shortlist_rate_percent", "Shortlist rate", "percent"),
    ("actionable_rate_percent", "Actionable rate", "percent"),
    ("actionability_gap_percent", "Actionability gap", "percent"),
    ("news_processed", "News processed", "count"),
    ("tweets_processed", "Tweets processed", "count"),
    ("bars_stored", "Bars stored", "count"),
    ("orders_placed", "Orders placed", "count"),
    ("broker_closed_positions", "Broker closed", "count"),
    ("broker_realized_pnl", "Broker realized P&L", "currency"),
]


class DashboardTrendService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.plan_repository = RecommendationPlanRepository(session)
        self.outcome_repository = RecommendationOutcomeRepository(session)
        self.effective_outcome_repository = EffectivePlanOutcomeRepository(session)
        self.trend_repository = DashboardTrendRepository(session)
        self.performance_metrics = TradingPerformanceMetricsService(session, self.effective_outcome_repository)

    def build_trends(self, *, now: datetime, days: int = 7) -> dict[str, object]:
        end_date = self._normalize_datetime(now).date() - timedelta(days=1)
        day_dates = [end_date - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
        snapshots = [self._ensure_daily_snapshot(day) for day in day_dates]
        return {
            "windows": [
                {"key": snapshot["snapshot_date"], "label": snapshot["snapshot_date"]}
                for snapshot in snapshots
            ],
            "series": [
                {
                    "key": key,
                    "label": label,
                    "kind": kind,
                    "values": [snapshot["dashboard_summary"].get(key) if key in snapshot["dashboard_summary"] else snapshot["technical_summary"].get(key) for snapshot in snapshots],
                }
                for key, label, kind in TREND_SERIES
            ],
        }

    def _ensure_daily_snapshot(self, snapshot_date: date) -> dict[str, object]:
        payload = self.trend_repository.get_snapshot(snapshot_date)
        if payload is not None:
            summary = payload.get("dashboard_summary") if isinstance(payload, dict) else None
            if isinstance(summary, dict) and "average_profit_percent" in summary:
                return payload
        payload = self._compute_daily_snapshot(snapshot_date)
        return self.trend_repository.upsert_snapshot(snapshot_date, payload)

    def _compute_daily_snapshot(self, snapshot_date: date) -> dict[str, object]:
        day_start = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        signals_amount = self._count_ticker_signals(computed_after=day_start, computed_before=day_end)
        plan_amount = self.plan_repository.count_plans(computed_after=day_start, computed_before=day_end)
        shortlisted_plans = self.plan_repository.count_plans(shortlisted=True, computed_after=day_start, computed_before=day_end)
        actionable_plans = self.plan_repository.count_plans(action="long", computed_after=day_start, computed_before=day_end) + self.plan_repository.count_plans(action="short", computed_after=day_start, computed_before=day_end)
        technical_plans = self.plan_repository.list_plans(limit=5000, computed_after=day_start, computed_before=day_end)

        news_processed = self._count_records(HistoricalNewsRecord, HistoricalNewsRecord.published_at, day_start, day_end)
        bars_stored = self._count_records(HistoricalMarketBarRecord, HistoricalMarketBarRecord.bar_time, day_start, day_end)
        orders_placed = self._count_records(BrokerOrderExecutionRecord, BrokerOrderExecutionRecord.created_at, day_start, day_end)
        broker_summary = self.performance_metrics.summarize_broker_closed_positions(evaluated_after=day_start, evaluated_before=day_end).to_dict()
        effective_summary = self.performance_metrics.summarize_effective_outcomes(evaluated_after=day_start, evaluated_before=day_end).to_dict()
        tweets_processed = self._sum_plan_item_count(technical_plans, "social_item_count")
        actionability = self.outcome_repository.summarize_actionability_diagnostics(evaluated_after=day_start, evaluated_before=day_end)

        dashboard_summary = {
            "plan_amount": plan_amount,
            "signals_amount": signals_amount,
            "shortlisted_plans": shortlisted_plans,
            "shortlist_rate_percent": self._percentage(plan_amount, signals_amount),
            "actionable_plans": actionable_plans,
            "actionable_rate_percent": self._percentage(actionable_plans, plan_amount),
            "overall_win_rate_percent": effective_summary["win_rate_percent"],
            "broker_win_rate_percent": broker_summary["win_rate_percent"],
            "total_profit": effective_summary["realized_pnl"],
            "average_profit_percent": effective_summary["average_return_percent"],
            "broker_realized_pnl": broker_summary["realized_pnl"],
            "broker_average_profit_percent": broker_summary["average_return_percent"],
            "simulated_average_profit_percent": effective_summary["simulation_average_return_percent"],
            "win_rate_percent": effective_summary["win_rate_percent"],
            "profit_percent": effective_summary["realized_pnl"],
            "win_rate_source": "effective",
            "profit_source": "effective",
            "actionability_gap_percent": actionability["actionability_gap_percent"],
            "actionable_win_rate_percent": actionability["actionable_win_rate_percent"],
            "phantom_win_rate_percent": actionability["phantom_win_rate_percent"],
            "actionable_resolved_outcomes": actionability["actionable_resolved_outcomes"],
            "phantom_resolved_outcomes": actionability["phantom_resolved_outcomes"],
            "actionable_win_outcomes": actionability["actionable_win_outcomes"],
            "actionable_loss_outcomes": actionability["actionable_loss_outcomes"],
            "phantom_win_outcomes": actionability["phantom_win_outcomes"],
            "phantom_loss_outcomes": actionability["phantom_loss_outcomes"],
            "no_action_outcomes": actionability["no_action_outcomes"],
            "watchlist_outcomes": actionability["watchlist_outcomes"],
        }
        technical_summary = {
            "news_processed": news_processed,
            "tweets_processed": tweets_processed,
            "bars_stored": bars_stored,
            "orders_placed": orders_placed,
            "broker_closed_positions": broker_summary["closed_positions"],
            "broker_wins": broker_summary["wins"],
            "broker_losses": broker_summary["losses"],
            "broker_realized_pnl": broker_summary["realized_pnl"],
        }
        return {
            "snapshot_date": snapshot_date.isoformat(),
            "computed_at": day_end.isoformat(),
            "dashboard_summary": dashboard_summary,
            "technical_summary": technical_summary,
        }

    def _count_ticker_signals(self, *, computed_after: datetime | None, computed_before: datetime | None) -> int:
        query = select(func.count()).select_from(TickerSignalSnapshotRecord)
        if computed_after is not None:
            query = query.where(TickerSignalSnapshotRecord.computed_at >= computed_after)
        if computed_before is not None:
            query = query.where(TickerSignalSnapshotRecord.computed_at < computed_before)
        return int(self.session.scalar(query) or 0)

    def _count_records(self, model, column, computed_after: datetime | None, computed_before: datetime | None) -> int:
        query = select(func.count()).select_from(model)
        if computed_after is not None:
            query = query.where(column >= computed_after)
        if computed_before is not None:
            query = query.where(column < computed_before)
        return int(self.session.scalar(query) or 0)

    @staticmethod
    def _sum_plan_item_count(plans: list, key: str) -> int:
        total = 0
        for plan in plans:
            breakdown = getattr(plan, "signal_breakdown", None)
            if hasattr(breakdown, "get"):
                try:
                    total += int(breakdown.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
        return total

    @staticmethod
    def _percentage(part: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round((part / total) * 100.0, 1)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

