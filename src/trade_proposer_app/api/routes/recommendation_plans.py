from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository

router = APIRouter(prefix="/recommendation-plans", tags=["recommendation-plans"])


@router.get("")
async def list_recommendation_plans(
    ticker: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[RecommendationPlan]:
    normalized_ticker = ticker.strip().upper() if ticker else None
    normalized_action = action.strip().lower() if action else None
    return RecommendationPlanRepository(session).list_plans(
        ticker=normalized_ticker,
        action=normalized_action,
        limit=limit,
        run_id=run_id,
    )
