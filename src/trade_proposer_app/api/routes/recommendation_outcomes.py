from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import (
    RecommendationCalibrationSummary,
    RecommendationEvidenceConcentrationSummary,
    RecommendationPlanOutcome,
    RecommendationSetupFamilyReviewSummary,
    RecommendationWalkForwardSummary,
)
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService
from trade_proposer_app.services.recommendation_walk_forward_validation import RecommendationWalkForwardValidationService

router = APIRouter(prefix="/recommendation-outcomes", tags=["recommendation-outcomes"])


@router.get("")
async def list_recommendation_outcomes(
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
    normalized_resolved = resolved.strip().lower() if resolved else None
    return EffectivePlanOutcomeRepository(session).list_outcomes(
        ticker=ticker.strip().upper() if ticker else None,
        outcome=outcome.strip().lower() if outcome else None,
        recommendation_plan_id=recommendation_plan_id,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=normalized_resolved,
        entry_touched=entry_touched,
        near_entry_miss=near_entry_miss,
        direction_worked_without_entry=direction_worked_without_entry,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/summary")
async def summarize_recommendation_outcomes(
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
    normalized_resolved = resolved.strip().lower() if resolved else None
    return RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=normalized_resolved,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/actionability-diagnostics")
async def summarize_recommendation_actionability_diagnostics(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, float | int | None]:
    return RecommendationOutcomeRepository(session).summarize_actionability_diagnostics(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
    )


@router.get("/calibration-report")
async def get_recommendation_calibration_report(
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
    normalized_resolved = resolved.strip().lower() if resolved else None
    summary = RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=normalized_resolved,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )
    return {
        "calibration_summary": summary,
        "calibration_report": summary.calibration_report,
    }


@router.get("/setup-family-review")
async def summarize_setup_family_review(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    resolved: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationSetupFamilyReviewSummary:
    normalized_resolved = resolved.strip().lower() if resolved else None
    return RecommendationSetupFamilyReviewService(EffectivePlanOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=normalized_resolved,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/evidence-concentration")
async def summarize_evidence_concentration(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    resolved: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationEvidenceConcentrationSummary:
    normalized_resolved = resolved.strip().lower() if resolved else None
    return RecommendationEvidenceConcentrationService(EffectivePlanOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        resolved=normalized_resolved,
        outcome=outcome.strip().lower() if outcome else None,
        evaluated_after=evaluated_after,
        evaluated_before=evaluated_before,
        limit=limit,
    )


@router.get("/walk-forward")
async def summarize_walk_forward_validation(
    setup_family: str | None = Query(default=None),
    lookback_days: int = Query(default=365, ge=30, le=3650),
    validation_days: int = Query(default=90, ge=7, le=365),
    step_days: int = Query(default=30, ge=1, le=365),
    min_resolved_outcomes: int = Query(default=20, ge=1, le=500),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationWalkForwardSummary:
    return RecommendationWalkForwardValidationService(
        EffectivePlanOutcomeRepository(session),
        RecommendationPlanRepository(session),
    ).summarize(
        setup_family=setup_family.strip().lower() if setup_family else None,
        lookback_days=lookback_days,
        validation_days=validation_days,
        step_days=step_days,
        min_resolved_outcomes=min_resolved_outcomes,
        limit=limit,
    )
