from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.gating_severity_alerts import GatingSeverityAlertService
from trade_proposer_app.services.recommendation_quality_summary import (
    RecommendationQualitySummaryService,
)

router = APIRouter(prefix="/recommendation-quality", tags=["recommendation-quality"])


@router.get("/summary")
def get_recommendation_quality_summary(
    session: Session = Depends(get_db_session),
    refresh: bool = Query(False, description="Force recomputing the cached quality summary"),
) -> dict[str, object]:
    payload = RecommendationQualitySummaryService(session).summarize(force_refresh=refresh)
    payload["gating_severity_alert"] = GatingSeverityAlertService(session).latest_alert()
    return payload
