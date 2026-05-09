from __future__ import annotations

from statistics import mean
from datetime import datetime, timezone

from trade_proposer_app.domain.models import (
    BrokerOrderExecution,
    BrokerPosition,
    RecommendationPlan,
    TickerAnalysisPage,
    TickerAnalysisSummary,
    TickerChartPoint,
    TickerChartSeries,
    TickerPerformanceSummary,
    TickerPlanChartOverlay,
)
from trade_proposer_app.domain.statuses import OutcomeStatus, ExecutionStatus, TradeOutcome
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.time_windows import normalize_review_window, review_window_start


class TickerAnalysisService:
    def __init__(
        self,
        recommendation_plans: RecommendationPlanRepository,
        broker_orders: BrokerOrderExecutionRepository | None = None,
        market_data: HistoricalMarketDataRepository | None = None,
        broker_positions: BrokerPositionRepository | None = None,
    ) -> None:
        self.recommendation_plans = recommendation_plans
        self.broker_orders = broker_orders or BrokerOrderExecutionRepository(recommendation_plans.session)
        self.market_data = market_data or HistoricalMarketDataRepository(recommendation_plans.session)
        self.broker_positions = broker_positions or BrokerPositionRepository(recommendation_plans.session)

    def get_ticker_page(
        self,
        ticker: str,
        *,
        window: str = "7d",
        selected_plan_ids: list[int] | None = None,
    ) -> TickerAnalysisPage:
        normalized_ticker = ticker.strip().upper()
        normalized_window = normalize_review_window(window, default="7d")
        now = datetime.now(timezone.utc)
        window_start = review_window_start(normalized_window, now)

        recommendation_plans = self.recommendation_plans.list_plans(
            ticker=normalized_ticker,
            limit=1000,
            computed_after=window_start,
            computed_before=now,
        )
        broker_orders = self.broker_orders.list_by_ticker(
            normalized_ticker,
            limit=1000,
            created_after=window_start,
            created_before=now,
        )
        broker_positions = self.broker_positions.list_by_ticker(normalized_ticker, limit=1000, exit_after=window_start, exit_before=now)
        bars = self.market_data.list_bars(
            ticker=normalized_ticker,
            timeframe="1m",
            start_at=window_start,
            end_at=now,
            limit=10_000,
        )
        selected = self._selected_plan_ids(recommendation_plans, selected_plan_ids)
        chart = TickerChartSeries(
            ticker=normalized_ticker,
            timeframe="1m",
            bars=bars,
            overlays=self._build_overlays(recommendation_plans, selected_plan_ids=selected),
            selected_plan_ids=selected,
        )

        stats = self.recommendation_plans.summarize_stats(
            ticker=normalized_ticker,
            window=normalized_window,
            computed_after=window_start,
            computed_before=now,
        )
        summary = self._build_summary(
            ticker=normalized_ticker,
            window=normalized_window,
            recommendation_plans=recommendation_plans,
            broker_orders=broker_orders,
            broker_positions=broker_positions,
            bars=bars,
            stats=stats,
            bars_count=self.market_data.count_bars(ticker=normalized_ticker, timeframe="1m", start_at=window_start, end_at=now),
            broker_order_count=self.broker_orders.count_by_ticker(normalized_ticker, created_after=window_start, created_before=now),
        )
        return TickerAnalysisPage(
            ticker=normalized_ticker,
            window=normalized_window,
            summary=summary,
            performance=self._build_performance_summary(normalized_ticker, recommendation_plans),
            chart=chart,
            broker_orders=broker_orders,
            recommendation_plans=recommendation_plans,
        )

    def _build_performance_summary(
        self,
        ticker: str,
        recommendation_plans: list[RecommendationPlan],
    ) -> TickerPerformanceSummary:
        confidence_values = [item.confidence_percent for item in recommendation_plans]

        return TickerPerformanceSummary(
            ticker=ticker,
            app_plan_count=len(recommendation_plans),
            actionable_plan_count=sum(1 for item in recommendation_plans if item.action in {"long", "short"}),
            long_plan_count=sum(1 for item in recommendation_plans if item.action == "long"),
            short_plan_count=sum(1 for item in recommendation_plans if item.action == "short"),
            no_action_plan_count=sum(1 for item in recommendation_plans if item.action == "no_action"),
            watchlist_plan_count=sum(1 for item in recommendation_plans if item.action == "watchlist"),
            open_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome is None or item.latest_outcome.status != OutcomeStatus.RESOLVED.value),
            win_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == TradeOutcome.WIN.value),
            loss_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == TradeOutcome.LOSS.value),
            warning_plan_count=sum(1 for item in recommendation_plans if item.warnings),
            average_confidence=round(mean(confidence_values), 2) if confidence_values else None,
        )

    def _build_summary(
        self,
        *,
        ticker: str,
        window: str,
        recommendation_plans: list[RecommendationPlan],
        broker_orders: list[BrokerOrderExecution],
        broker_positions: list[BrokerPosition],
        bars: list,
        stats,
        bars_count: int,
        broker_order_count: int,
    ) -> TickerAnalysisSummary:
        resolved = [item for item in recommendation_plans if self._plan_state(item)[0] in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        real_resolved = [item for item in recommendation_plans if self._plan_resolution_source(item) == "broker" and self._plan_state(item)[0] in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        simulated_resolved = [item for item in recommendation_plans if self._plan_resolution_source(item) == "simulated" and self._plan_state(item)[0] in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}]
        wins = sum(1 for item in resolved if self._plan_state(item)[0] == TradeOutcome.WIN.value)
        real_wins = sum(1 for item in real_resolved if self._plan_state(item)[0] == TradeOutcome.WIN.value)
        simulated_wins = sum(1 for item in simulated_resolved if self._plan_state(item)[0] == TradeOutcome.WIN.value)
        real_profit = round(sum(float(position.realized_pnl or 0.0) for position in broker_positions), 4) if broker_positions else 0.0
        simulated_profit = round(sum(self._simulated_profit(item) for item in simulated_resolved), 4)
        total_profit = round(real_profit + simulated_profit, 4)
        return TickerAnalysisSummary(
            ticker=ticker,
            window=window,
            plan_count=int(getattr(stats, "total_plans", len(recommendation_plans)) or len(recommendation_plans)),
            actionable_plan_count=stats.actionable_plan_count if hasattr(stats, "actionable_plan_count") else sum(1 for item in recommendation_plans if item.action in {"long", "short"}),
            broker_order_count=broker_order_count,
            bar_count=bars_count,
            resolved_plan_count=len(resolved),
            open_plan_count=len(recommendation_plans) - len(resolved),
            win_rate_percent=round((wins / len(resolved)) * 100.0, 1) if resolved else None,
            total_profit=total_profit,
            real_resolved_plan_count=len(real_resolved),
            simulated_resolved_plan_count=len(simulated_resolved),
            real_win_rate_percent=round((real_wins / len(real_resolved)) * 100.0, 1) if real_resolved else None,
            simulated_win_rate_percent=round((simulated_wins / len(simulated_resolved)) * 100.0, 1) if simulated_resolved else None,
            real_profit=round(real_profit, 4),
            simulated_profit=round(simulated_profit, 4),
        )

    def _build_overlays(self, recommendation_plans: list[RecommendationPlan], *, selected_plan_ids: list[int]) -> list[TickerPlanChartOverlay]:
        overlays: list[TickerPlanChartOverlay] = []
        selected_set = set(selected_plan_ids)
        for plan in recommendation_plans:
            if plan.action not in {"long", "short"} or plan.id is None:
                continue
            state, resolved_result, entered = self._plan_state(plan)
            entry = self._entry_price(plan)
            stop = plan.stop_loss
            take = plan.take_profit
            color = self._color_for_state(state)
            points: list[TickerChartPoint] = []
            points.append(TickerChartPoint(kind="entry", x=plan.computed_at, y=entry, label="entry", color=color))
            if state == "open" and entered:
                if stop is not None:
                    points.append(TickerChartPoint(kind="stop_loss", x=plan.computed_at, y=float(stop), label="stop_loss", color="#ef4444"))
                if take is not None:
                    points.append(TickerChartPoint(kind="take_profit", x=plan.computed_at, y=float(take), label="take_profit", color="#22c55e"))
            elif resolved_result in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}:
                resolution_price = float(take if resolved_result == TradeOutcome.WIN.value else stop or entry)
                resolution_x = self._resolution_time(plan)
                points.append(TickerChartPoint(kind="resolution", x=resolution_x, y=resolution_price, label=resolved_result, color=color))
            overlays.append(
                TickerPlanChartOverlay(
                    plan_id=plan.id,
                    ticker=plan.ticker,
                    action=plan.action,
                    label=f"{plan.ticker} {plan.action} #{plan.id}",
                    selected=(plan.id in selected_set),
                    color=color,
                    resolution_source=self._plan_resolution_source(plan),
                    state=state,
                    points=points,
                )
            )
        return overlays

    def _selected_plan_ids(self, recommendation_plans: list[RecommendationPlan], selected_plan_ids: list[int] | None) -> list[int]:
        if selected_plan_ids:
            return [plan_id for plan_id in selected_plan_ids if isinstance(plan_id, int)]
        return [plan.id for plan in recommendation_plans if plan.id is not None and plan.action in {"long", "short"}]

    def _plan_state(self, plan: RecommendationPlan) -> tuple[str, str | None, bool]:
        outcome = plan.latest_outcome
        broker_status = str(plan.broker_order_status or "").strip().lower()
        outcome_value = str(outcome.outcome or "").strip().lower() if outcome is not None else None
        if outcome is not None and outcome.status == OutcomeStatus.RESOLVED.value and outcome_value in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}:
            return outcome_value, outcome_value, True
        if broker_status in {TradeOutcome.WIN.value, TradeOutcome.LOSS.value}:
            return broker_status, broker_status, True
        entered = bool(
            (outcome is not None and outcome.entry_touched)
            or broker_status in {ExecutionStatus.OPEN.value, TradeOutcome.WIN.value, TradeOutcome.LOSS.value}
        )
        if entered:
            return "open", None, True
        return "pending", None, False

    def _plan_resolution_source(self, plan: RecommendationPlan) -> str:
        source = str(plan.effective_evaluation_source or "").strip().lower()
        if source in {"broker", "simulated"}:
            return source
        if plan.broker_order_status:
            return "broker"
        if plan.latest_outcome is not None:
            return "simulated"
        return "missing"

    @staticmethod
    def _entry_price(plan: RecommendationPlan) -> float:
        if plan.entry_price_low is not None and plan.entry_price_high is not None:
            return round((float(plan.entry_price_low) + float(plan.entry_price_high)) / 2.0, 4)
        if plan.entry_price_low is not None:
            return float(plan.entry_price_low)
        if plan.entry_price_high is not None:
            return float(plan.entry_price_high)
        return 0.0

    @staticmethod
    def _resolution_time(plan: RecommendationPlan) -> datetime:
        if plan.latest_outcome is not None and plan.latest_outcome.evaluated_at is not None:
            return plan.latest_outcome.evaluated_at
        if plan.broker_order_updated_at is not None:
            return plan.broker_order_updated_at
        return plan.computed_at

    @staticmethod
    def _simulated_profit(plan: RecommendationPlan) -> float:
        outcome = plan.latest_outcome
        if outcome is None or outcome.status != OutcomeStatus.RESOLVED.value:
            return 0.0
        value = outcome.horizon_return_5d
        return float(value or 0.0)

    @staticmethod
    def _color_for_state(state: str) -> str:
        return {
            "win": "#16a34a",
            "loss": "#dc2626",
            "open": "#2563eb",
            "pending": "#f59e0b",
        }.get(state, "#6b7280")
