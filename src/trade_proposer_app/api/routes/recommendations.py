from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import Recommendation, Run, RunDiagnostics
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.builders import create_proposal_service
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.evaluations import RecommendationEvaluationService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.optimizations import WeightOptimizationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def list_recommendations(session: Session = Depends(get_db_session)) -> list[Recommendation]:
    return RunRepository(session).list_latest_recommendations(limit=50)


@router.get("/{recommendation_id}")
async def get_recommendation(recommendation_id: int, session: Session = Depends(get_db_session)) -> dict[str, Recommendation | Run | RunDiagnostics]:
    repository = RunRepository(session)
    try:
        recommendation = repository.get_recommendation(recommendation_id)
        run = repository.get_run(recommendation.run_id or 0)
        diagnostics = repository.get_recommendation_diagnostics(recommendation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "recommendation": recommendation,
        "run": run,
        "diagnostics": diagnostics,
    }


def create_evaluation_job_execution_service(session: Session) -> JobExecutionService:
    settings_repository = SettingsRepository(session)
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        proposals=create_proposal_service(session),
        evaluations=EvaluationExecutionService(
            recommendation_evaluations=RecommendationEvaluationService(session),
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        optimizations=WeightOptimizationService(
            session=session,
            minimum_resolved_trades=settings_repository.get_optimization_minimum_resolved_trades(),
        ),
        recommendation_plans=RecommendationPlanRepository(session),
    )


@router.post("/evaluate")
async def evaluate_recommendations(session: Session = Depends(get_db_session)) -> Run:
    try:
        return create_evaluation_job_execution_service(session).enqueue_manual_evaluation()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{recommendation_id}/evaluate")
async def evaluate_recommendation(recommendation_id: int, session: Session = Depends(get_db_session)) -> Run:
    try:
        return create_evaluation_job_execution_service(session).enqueue_manual_evaluation(recommendation_id=recommendation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
