from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import TickerAnalysisPage
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.tickers import TickerAnalysisService

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("/{ticker}")
async def get_ticker_page(ticker: str, session: Session = Depends(get_db_session)) -> TickerAnalysisPage:
    return TickerAnalysisService(RecommendationPlanRepository(session)).get_ticker_page(ticker)
