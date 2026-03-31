from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import (
    RecommendationCalibrationSummary,
    RecommendationEvidenceConcentrationSummary,
    RecommendationPlanOutcome,
    RecommendationSetupFamilyReviewSummary,
)
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService

router = APIRouter(prefix="/recommendation-outcomes", tags=["recommendation-outcomes"])


@router.get("")
async def list_recommendation_outcomes(
    ticker: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    recommendation_plan_id: int | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> list[RecommendationPlanOutcome]:
    return RecommendationOutcomeRepository(session).list_outcomes(
        ticker=ticker.strip().upper() if ticker else None,
        outcome=outcome.strip().lower() if outcome else None,
        recommendation_plan_id=recommendation_plan_id,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        limit=limit,
    )


@router.get("/summary")
async def summarize_recommendation_outcomes(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationCalibrationSummary:
    return RecommendationPlanCalibrationService(RecommendationOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        limit=limit,
    )


@router.get("/setup-family-review")
async def summarize_setup_family_review(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationSetupFamilyReviewSummary:
    return RecommendationSetupFamilyReviewService(RecommendationOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        limit=limit,
    )


@router.get("/evidence-concentration")
async def summarize_evidence_concentration(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationEvidenceConcentrationSummary:
    return RecommendationEvidenceConcentrationService(RecommendationOutcomeRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        limit=limit,
    )
