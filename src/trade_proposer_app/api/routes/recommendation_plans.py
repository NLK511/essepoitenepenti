from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationBaselineSummary, RecommendationPlan, RecommendationPlanStats, Run
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.optimizations import WeightOptimizationService
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService

router = APIRouter(prefix="/recommendation-plans", tags=["recommendation-plans"])


@router.get("/stats")
async def recommendation_plan_stats(session: Session = Depends(get_db_session)) -> RecommendationPlanStats:
    plans = RecommendationPlanRepository(session)
    outcomes = RecommendationOutcomeRepository(session)
    counts = outcomes.count_outcomes()
    return RecommendationPlanStats(total_plans=plans.count_plans(), **counts)


@router.get("")
async def list_recommendation_plans(
    ticker: str | None = Query(default=None),
    action: str | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    plan_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[RecommendationPlan]:
    normalized_ticker = ticker.strip().upper() if ticker else None
    normalized_action = action.strip().lower() if action else None
    normalized_setup_family = setup_family.strip().lower() if setup_family else None
    return RecommendationPlanRepository(session).list_plans(
        ticker=normalized_ticker,
        action=normalized_action,
        setup_family=normalized_setup_family,
        limit=limit,
        run_id=run_id,
        plan_id=plan_id,
    )


@router.get("/baselines")
async def summarize_recommendation_plan_baselines(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> RecommendationBaselineSummary:
    return RecommendationPlanBaselineService(RecommendationPlanRepository(session)).summarize(
        ticker=ticker.strip().upper() if ticker else None,
        run_id=run_id,
        setup_family=setup_family.strip().lower() if setup_family else None,
        limit=limit,
    )


def create_evaluation_job_execution_service(session: Session) -> JobExecutionService:
    settings_repository = SettingsRepository(session)
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        evaluations=EvaluationExecutionService(
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        optimizations=WeightOptimizationService(
            session=session,
            minimum_resolved_trades=settings_repository.get_optimization_minimum_resolved_trades(),
        ),
        recommendation_plans=RecommendationPlanRepository(session),
    )


@router.post("/evaluate")
async def evaluate_recommendation_plans(session: Session = Depends(get_db_session)) -> Run:
    try:
        return create_evaluation_job_execution_service(session).enqueue_manual_evaluation(recommendation_plan_scope=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{recommendation_plan_id}/evaluate")
async def evaluate_recommendation_plan(recommendation_plan_id: int, session: Session = Depends(get_db_session)) -> Run:
    try:
        return create_evaluation_job_execution_service(session).enqueue_manual_evaluation(
            recommendation_plan_id=recommendation_plan_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
