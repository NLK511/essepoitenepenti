from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.recommendation_plan_calibration import (
    RecommendationPlanCalibrationService,
)

router = APIRouter(prefix="/calibration", tags=["calibration"])


@router.get("/confidence")
async def get_confidence_calibration(
    mode: str = Query(default="broker_only"),
    window: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    computed_after: datetime | None = Query(default=None),
    computed_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=10000),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)).confidence_report(
        mode=mode,
        window=window,
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        computed_after=computed_after,
        computed_before=computed_before,
        limit=limit,
    )
