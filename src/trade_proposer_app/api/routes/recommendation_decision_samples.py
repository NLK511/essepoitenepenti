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
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = RecommendationDecisionSampleRepository(session)
    normalized_ticker = ticker.strip().upper() if ticker else None
    normalized_decision_type = decision_type.strip().lower() if decision_type else None
    normalized_review_priority = review_priority.strip().lower() if review_priority else None
    items = repository.list_samples(
        ticker=normalized_ticker,
        run_id=run_id,
        decision_type=normalized_decision_type,
        review_priority=normalized_review_priority,
        limit=limit,
        offset=offset,
    )
    total = repository.count_samples(
        ticker=normalized_ticker,
        run_id=run_id,
        decision_type=normalized_decision_type,
        review_priority=normalized_review_priority,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}
