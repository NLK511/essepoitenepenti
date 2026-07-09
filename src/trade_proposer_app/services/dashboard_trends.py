from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

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
        self.performance_metrics = TradingPerformanceMetricsService(
            session, self.effective_outcome_repository
        )

    def build_trends(self, *, now: datetime, days: int = 7) -> dict[str, object]:
        snapshots = self._daily_snapshots_for_window(now=now, days=days, include_today=False)
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
                    "values": [
                        snapshot["dashboard_summary"].get(key)
                        if key in snapshot["dashboard_summary"]
                        else snapshot["technical_summary"].get(key)
                        for snapshot in snapshots
                    ],
                }
                for key, label, kind in TREND_SERIES
            ],
        }

    def build_cached_window_metrics(
        self, *, now: datetime, days: int
    ) -> dict[str, dict[str, object]]:
        """Build weekly/monthly dashboard metrics from daily snapshots plus today's partial day.

        Long dashboard windows used to rescan all underlying rows on every page load. This
        method keeps the same payload shape but reads at most one live partial day and a
        bounded set of daily aggregate snapshots.
        """
        snapshots = self._daily_snapshots_for_window(now=now, days=days, include_today=True)
        return {
            "window_key": f"{days}d",
            "dashboard_summary": self._aggregate_dashboard_summaries(snapshots),
            "technical_summary": self._aggregate_technical_summaries(snapshots),
        }

    def _daily_snapshots_for_window(
        self, *, now: datetime, days: int, include_today: bool
    ) -> list[dict[str, object]]:
        normalized_now = self._normalize_datetime(now)
        end_date = (
            normalized_now.date() if include_today else normalized_now.date() - timedelta(days=1)
        )
        day_dates = [end_date - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
        snapshots: list[dict[str, object]] = []
        for snapshot_date in day_dates:
            if include_today and snapshot_date == normalized_now.date():
                snapshots.append(self._compute_partial_day_snapshot(snapshot_date, normalized_now))
            else:
                snapshots.append(self._ensure_daily_snapshot(snapshot_date))
        return snapshots

    def _ensure_daily_snapshot(self, snapshot_date: date) -> dict[str, object]:
        payload = self.trend_repository.get_snapshot(snapshot_date)
        if payload is not None:
            summary = payload.get("dashboard_summary") if isinstance(payload, dict) else None
            if isinstance(summary, dict) and "average_profit_percent" in summary:
                return payload
        payload = self._compute_daily_snapshot(snapshot_date)
        return self.trend_repository.upsert_snapshot(snapshot_date, payload)

    def _compute_daily_snapshot(self, snapshot_date: date) -> dict[str, object]:
        day_start = datetime.combine(snapshot_date, time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        return self._compute_snapshot_between(snapshot_date, day_start, day_end)

    def _compute_partial_day_snapshot(
        self, snapshot_date: date, now: datetime
    ) -> dict[str, object]:
        day_start = datetime.combine(snapshot_date, time.min, tzinfo=UTC)
        return self._compute_snapshot_between(snapshot_date, day_start, now)

    def _compute_snapshot_between(
        self, snapshot_date: date, day_start: datetime, day_end: datetime
    ) -> dict[str, object]:
        signals_amount = self._count_ticker_signals(
            computed_after=day_start, computed_before=day_end
        )
        plan_amount = self.plan_repository.count_plans(
            computed_after=day_start, computed_before=day_end
        )
        shortlisted_plans = self.plan_repository.count_plans(
            shortlisted=True, computed_after=day_start, computed_before=day_end
        )
        actionable_plans = self.plan_repository.count_plans(
            action="long", computed_after=day_start, computed_before=day_end
        ) + self.plan_repository.count_plans(
            action="short", computed_after=day_start, computed_before=day_end
        )
        technical_plans = self.plan_repository.list_plans(
            limit=5000, computed_after=day_start, computed_before=day_end
        )

        news_processed = self._count_news_processed(day_start, day_end)
        bars_stored = self._count_records(
            HistoricalMarketBarRecord, HistoricalMarketBarRecord.bar_time, day_start, day_end
        )
        orders_placed = self._count_records(
            BrokerOrderExecutionRecord, BrokerOrderExecutionRecord.created_at, day_start, day_end
        )
        broker_summary = self.performance_metrics.summarize_broker_closed_positions(
            evaluated_after=day_start, evaluated_before=day_end
        ).to_dict()
        effective_summary = self.performance_metrics.summarize_effective_outcomes(
            evaluated_after=day_start, evaluated_before=day_end
        ).to_dict()
        tweets_processed = self._sum_plan_item_count(technical_plans, "social_item_count")
        actionability = self.outcome_repository.summarize_actionability_diagnostics(
            evaluated_after=day_start, evaluated_before=day_end
        )

        dashboard_summary = {
            "plan_amount": plan_amount,
            "signals_amount": signals_amount,
            "shortlisted_plans": shortlisted_plans,
            "shortlist_rate_percent": self._percentage(plan_amount, signals_amount),
            "actionable_plans": actionable_plans,
            "actionable_rate_percent": self._percentage(actionable_plans, plan_amount),
            "overall_win_rate_percent": effective_summary["win_rate_percent"],
            "broker_win_rate_percent": broker_summary["win_rate_percent"],
            "effective_closed_positions": effective_summary["resolved_outcomes"],
            "effective_wins": effective_summary["wins"],
            "effective_losses": effective_summary["losses"],
            "total_profit": effective_summary["realized_pnl"],
            "average_profit_percent": effective_summary["average_return_percent"],
            "broker_realized_pnl": broker_summary["realized_pnl"],
            "broker_average_profit_percent": broker_summary["average_return_percent"],
            "simulated_average_profit_percent": effective_summary[
                "simulation_average_return_percent"
            ],
            "win_rate_percent": effective_summary["win_rate_percent"],
            "profit_percent": effective_summary["average_return_percent"],
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
            "effective_closed_positions": effective_summary["resolved_outcomes"],
            "effective_wins": effective_summary["wins"],
            "effective_losses": effective_summary["losses"],
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

    def _aggregate_dashboard_summaries(
        self, snapshots: list[dict[str, object]]
    ) -> dict[str, object]:
        summaries = [snapshot.get("dashboard_summary") for snapshot in snapshots]
        rows = [summary for summary in summaries if isinstance(summary, dict)]
        plan_amount = self._sum(rows, "plan_amount")
        signals_amount = self._sum(rows, "signals_amount")
        shortlisted_plans = self._sum(rows, "shortlisted_plans")
        actionable_plans = self._sum(rows, "actionable_plans")
        effective_closed = self._sum(rows, "effective_closed_positions")
        effective_wins = self._sum(rows, "effective_wins")
        broker_closed = self._sum(rows, "broker_closed_positions")
        broker_wins = self._sum(rows, "broker_wins")
        total_profit = self._sum_float(rows, "total_profit")
        broker_realized_pnl = self._sum_float(rows, "broker_realized_pnl")
        return {
            "plan_amount": plan_amount,
            "signals_amount": signals_amount,
            "shortlisted_plans": shortlisted_plans,
            "shortlist_rate_percent": self._percentage(plan_amount, signals_amount),
            "actionable_plans": actionable_plans,
            "actionable_rate_percent": self._percentage(actionable_plans, plan_amount),
            "overall_win_rate_percent": self._percentage(effective_wins, effective_closed),
            "broker_win_rate_percent": self._percentage(broker_wins, broker_closed),
            "effective_closed_positions": effective_closed,
            "effective_wins": effective_wins,
            "effective_losses": self._sum(rows, "effective_losses"),
            "total_profit": total_profit,
            "average_profit_percent": self._weighted_average(
                rows, "average_profit_percent", "effective_closed_positions"
            ),
            "broker_realized_pnl": broker_realized_pnl,
            "broker_average_profit_percent": self._weighted_average(
                rows, "broker_average_profit_percent", "broker_closed_positions"
            ),
            "simulated_average_profit_percent": self._weighted_average(
                rows, "simulated_average_profit_percent", "effective_closed_positions"
            ),
            "win_rate_percent": self._percentage(effective_wins, effective_closed),
            "profit_percent": self._weighted_average(
                rows, "average_profit_percent", "effective_closed_positions"
            ),
            "win_rate_source": "effective_aggregate",
            "profit_source": "effective_aggregate",
            "actionability_gap_percent": self._weighted_average(
                rows, "actionability_gap_percent", "plan_amount"
            ),
            "actionable_win_rate_percent": self._weighted_average(
                rows, "actionable_win_rate_percent", "actionable_resolved_outcomes"
            ),
            "phantom_win_rate_percent": self._weighted_average(
                rows, "phantom_win_rate_percent", "phantom_resolved_outcomes"
            ),
            "actionable_resolved_outcomes": self._sum(rows, "actionable_resolved_outcomes"),
            "phantom_resolved_outcomes": self._sum(rows, "phantom_resolved_outcomes"),
            "actionable_win_outcomes": self._sum(rows, "actionable_win_outcomes"),
            "actionable_loss_outcomes": self._sum(rows, "actionable_loss_outcomes"),
            "phantom_win_outcomes": self._sum(rows, "phantom_win_outcomes"),
            "phantom_loss_outcomes": self._sum(rows, "phantom_loss_outcomes"),
            "no_action_outcomes": self._sum(rows, "no_action_outcomes"),
            "watchlist_outcomes": self._sum(rows, "watchlist_outcomes"),
            "aggregate_source": "daily_snapshots_plus_today",
        }

    def _aggregate_technical_summaries(
        self, snapshots: list[dict[str, object]]
    ) -> dict[str, object]:
        summaries = [snapshot.get("technical_summary") for snapshot in snapshots]
        rows = [summary for summary in summaries if isinstance(summary, dict)]
        return {
            "news_processed": self._sum(rows, "news_processed"),
            "tweets_processed": self._sum(rows, "tweets_processed"),
            "bars_stored": self._sum(rows, "bars_stored"),
            "orders_placed": self._sum(rows, "orders_placed"),
            "effective_closed_positions": self._sum(rows, "effective_closed_positions"),
            "effective_wins": self._sum(rows, "effective_wins"),
            "effective_losses": self._sum(rows, "effective_losses"),
            "broker_closed_positions": self._sum(rows, "broker_closed_positions"),
            "broker_wins": self._sum(rows, "broker_wins"),
            "broker_losses": self._sum(rows, "broker_losses"),
            "broker_realized_pnl": self._sum_float(rows, "broker_realized_pnl"),
            "aggregate_source": "daily_snapshots_plus_today",
        }

    @staticmethod
    def _sum(rows: list[dict[str, object]], key: str) -> int:
        total = 0
        for row in rows:
            try:
                total += int(row.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _sum_float(rows: list[dict[str, object]], key: str) -> float:
        total = 0.0
        for row in rows:
            try:
                total += float(row.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        return round(total, 4)

    def _weighted_average(
        self, rows: list[dict[str, object]], key: str, weight_key: str
    ) -> float | None:
        weighted_sum = 0.0
        weight_sum = 0
        for row in rows:
            value = row.get(key)
            weight = row.get(weight_key)
            if value is None or weight is None:
                continue
            try:
                numeric_value = float(value)
                numeric_weight = int(weight)
            except (TypeError, ValueError):
                continue
            if numeric_weight <= 0:
                continue
            weighted_sum += numeric_value * numeric_weight
            weight_sum += numeric_weight
        if weight_sum <= 0:
            return None
        return round(weighted_sum / weight_sum, 2)

    def _count_ticker_signals(
        self, *, computed_after: datetime | None, computed_before: datetime | None
    ) -> int:
        query = select(func.count()).select_from(TickerSignalSnapshotRecord)
        if computed_after is not None:
            query = query.where(TickerSignalSnapshotRecord.computed_at >= computed_after)
        if computed_before is not None:
            query = query.where(TickerSignalSnapshotRecord.computed_at < computed_before)
        return int(self.session.scalar(query) or 0)

    def _count_records(
        self, model, column, computed_after: datetime | None, computed_before: datetime | None
    ) -> int:
        query = select(func.count()).select_from(model)
        if computed_after is not None:
            query = query.where(column >= computed_after)
        if computed_before is not None:
            query = query.where(column < computed_before)
        return int(self.session.scalar(query) or 0)

    def _count_news_processed(self, computed_after: datetime | None, computed_before: datetime | None) -> int:
        processed_at = func.coalesce(
            HistoricalNewsRecord.ingested_at,
            HistoricalNewsRecord.created_at,
            HistoricalNewsRecord.published_at,
        )
        query = select(func.count()).select_from(HistoricalNewsRecord)
        if computed_after is not None:
            query = query.where(processed_at >= computed_after)
        if computed_before is not None:
            query = query.where(processed_at < computed_before)
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
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
