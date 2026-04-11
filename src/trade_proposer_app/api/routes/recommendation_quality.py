from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.recommendation_quality_summary import RecommendationQualitySummaryService

router = APIRouter(prefix="/recommendation-quality", tags=["recommendation-quality"])


@router.get("/summary")
async def get_recommendation_quality_summary(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return RecommendationQualitySummaryService(session).summarize()
