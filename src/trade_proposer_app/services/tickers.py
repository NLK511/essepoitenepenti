from statistics import mean

from trade_proposer_app.domain.models import RecommendationPlan, TickerAnalysisPage, TickerPerformanceSummary
from trade_proposer_app.domain.statuses import OutcomeStatus, TradeOutcome
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository


class TickerAnalysisService:
    def __init__(self, recommendation_plans: RecommendationPlanRepository) -> None:
        self.recommendation_plans = recommendation_plans

    def get_ticker_page(self, ticker: str) -> TickerAnalysisPage:
        normalized_ticker = ticker.strip().upper()
        recommendation_plans = self.recommendation_plans.list_plans(ticker=normalized_ticker, limit=200)
        return TickerAnalysisPage(
            ticker=normalized_ticker,
            performance=self._build_performance_summary(normalized_ticker, recommendation_plans),
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
            open_plan_count=sum(
                1
                for item in recommendation_plans
                if item.latest_outcome is None or item.latest_outcome.status != OutcomeStatus.RESOLVED.value
            ),
            win_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == TradeOutcome.WIN.value),
            loss_plan_count=sum(1 for item in recommendation_plans if item.latest_outcome and item.latest_outcome.outcome == TradeOutcome.LOSS.value),
            warning_plan_count=sum(1 for item in recommendation_plans if item.warnings),
            average_confidence=round(mean(confidence_values), 2) if confidence_values else None,
        )
