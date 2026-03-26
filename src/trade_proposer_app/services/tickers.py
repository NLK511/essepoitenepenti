import sqlite3
from pathlib import Path
from statistics import mean

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import PrototypeTradeLogEntry, RecommendationPlan, TickerAnalysisPage, TickerPerformanceSummary
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository


class TickerAnalysisService:
    def __init__(self, recommendation_plans: RecommendationPlanRepository) -> None:
        self.recommendation_plans = recommendation_plans

    def get_ticker_page(self, ticker: str) -> TickerAnalysisPage:
        normalized_ticker = ticker.strip().upper()
        recommendation_plans = self.recommendation_plans.list_plans(ticker=normalized_ticker, limit=200)
        prototype_trades = self._list_prototype_trades(normalized_ticker)
        return TickerAnalysisPage(
            ticker=normalized_ticker,
            performance=self._build_performance_summary(normalized_ticker, recommendation_plans, prototype_trades),
            recommendation_plans=recommendation_plans,
            prototype_trades=prototype_trades,
        )

    @staticmethod
    def get_prototype_trade_log_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "data"
            / "trade_log.db"
        )

    def _list_prototype_trades(self, ticker: str) -> list[PrototypeTradeLogEntry]:
        trade_log_path = self.get_prototype_trade_log_path()
        if not trade_log_path.exists():
            return []

        connection = sqlite3.connect(trade_log_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, timestamp, ticker, direction, entry_price, stop_loss, take_profit,
                       confidence, status, close_timestamp, duration_days, analysis_json
                FROM trades
                WHERE UPPER(ticker) = ?
                ORDER BY timestamp DESC, id DESC
                """,
                (ticker,),
            ).fetchall()
        finally:
            connection.close()

        entries: list[PrototypeTradeLogEntry] = []
        for row in rows:
            entries.append(
                PrototypeTradeLogEntry(
                    id=int(row["id"]),
                    timestamp=str(row["timestamp"]),
                    ticker=str(row["ticker"]),
                    direction=str(row["direction"]),
                    entry_price=float(row["entry_price"]),
                    stop_loss=float(row["stop_loss"]),
                    take_profit=float(row["take_profit"]),
                    confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                    status=str(row["status"]),
                    close_timestamp=str(row["close_timestamp"]) if row["close_timestamp"] else None,
                    duration_days=float(row["duration_days"]) if row["duration_days"] is not None else None,
                    analysis_json=str(row["analysis_json"]) if row["analysis_json"] else None,
                )
            )
        return entries

    def _build_performance_summary(
        self,
        ticker: str,
        recommendation_plans: list[RecommendationPlan],
        prototype_trades: list[PrototypeTradeLogEntry],
    ) -> TickerPerformanceSummary:
        resolved_trades = [trade for trade in prototype_trades if trade.status in {"WIN", "LOSS"}]
        wins = [trade for trade in resolved_trades if trade.status == "WIN"]
        losses = [trade for trade in resolved_trades if trade.status == "LOSS"]
        pending_trades = [trade for trade in prototype_trades if trade.status == "PENDING"]
        confidence_values = [item.confidence_percent for item in recommendation_plans]
        resolved_durations = [trade.duration_days for trade in resolved_trades if trade.duration_days is not None]

        return TickerPerformanceSummary(
            ticker=ticker,
            app_plan_count=len(recommendation_plans),
            actionable_plan_count=sum(1 for item in recommendation_plans if item.action in {"long", "short"}),
            long_plan_count=sum(1 for item in recommendation_plans if item.action == "long"),
            short_plan_count=sum(1 for item in recommendation_plans if item.action == "short"),
            no_action_plan_count=sum(1 for item in recommendation_plans if item.action == "no_action"),
            watchlist_plan_count=sum(1 for item in recommendation_plans if item.action == "watchlist"),
            open_plan_count=sum(
                1
                for item in recommendation_plans
                if item.latest_outcome is None or item.latest_outcome.status not in {"resolved"}
            ),
            win_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == "win"),
            loss_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == "loss"),
            warning_plan_count=sum(1 for item in recommendation_plans if item.warnings),
            average_confidence=round(mean(confidence_values), 2) if confidence_values else None,
            prototype_trade_log_path=str(self.get_prototype_trade_log_path()),
            prototype_trade_log_available=self.get_prototype_trade_log_path().exists(),
            prototype_trade_count=len(prototype_trades),
            resolved_trade_count=len(resolved_trades),
            win_count=len(wins),
            loss_count=len(losses),
            pending_trade_count=len(pending_trades),
            win_rate_percent=round((len(wins) / len(resolved_trades)) * 100.0, 2) if resolved_trades else None,
            average_resolved_duration_days=round(mean(resolved_durations), 2) if resolved_durations else None,
        )
