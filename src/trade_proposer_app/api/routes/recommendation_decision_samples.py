from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationDecisionSample
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository

router = APIRouter(prefix="/recommendation-decision-samples", tags=["recommendation-decision-samples"])


@router.get("")
async def list_recommendation_decision_samples(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    decision_type: str | None = Query(default=None),
    review_priority: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[RecommendationDecisionSample]:
    return RecommendationDecisionSampleRepository(session).list_samples(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        decision_type=decision_type.strip().lower() if decision_type else None,
        review_priority=review_priority.strip().lower() if review_priority else None,
        limit=limit,
    )
