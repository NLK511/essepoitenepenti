from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationCalibrationSummary, RecommendationPlanOutcome
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService

router = APIRouter(prefix="/effective-plan-outcomes", tags=["effective-plan-outcomes"])


@router.get("")
async def list_effective_plan_outcomes(
    ticker: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    recommendation_plan_id: int | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    resolved: str | None = Query(default=None),
    entry_touched: bool | None = Query(default=None),
    near_entry_miss: bool | None = Query(default=None),
    direction_worked_without_entry: bool | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> list[RecommendationPlanOutcome]:
    return EffectivePlanOutcomeRepository(session).list_outcomes(
        ticker=ticker.strip().upper() if ticker else None,
        outcome=outcome.strip().lower() if outcome else None,
        recommendation_plan_id=recommendation_plan_id,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=resolved.strip().lower() if resolved else None,
        entry_touched=entry_touched,
        near_entry_miss=near_entry_miss,
        direction_worked_without_entry=direction_worked_without_entry,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/summary")
async def summarize_effective_plan_outcomes(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    resolved: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationCalibrationSummary:
    return RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=resolved.strip().lower() if resolved else None,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/calibration-report")
async def get_effective_plan_calibration_report(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    resolved: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    summary = await summarize_effective_plan_outcomes(
        ticker=ticker,
        run_id=run_id,
        setup_family=setup_family,
        resolved=resolved,
        outcome=outcome,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
        session=session,
    )
    return {"calibration_summary": summary, "calibration_report": summary.calibration_report}
