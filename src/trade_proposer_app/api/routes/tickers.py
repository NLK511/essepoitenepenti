from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import TickerAnalysisPage
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.tickers import TickerAnalysisService

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("/{ticker}")
async def get_ticker_page(
    ticker: str,
    window: str = Query(default="7d"),
    selected_plan_ids: list[int] | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> TickerAnalysisPage:
    return TickerAnalysisService(
        RecommendationPlanRepository(session),
        BrokerOrderExecutionRepository(session),
        HistoricalMarketDataRepository(session),
        BrokerPositionRepository(session),
    ).get_ticker_page(ticker, window=window, selected_plan_ids=selected_plan_ids)
