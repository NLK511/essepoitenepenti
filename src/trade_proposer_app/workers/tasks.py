import traceback
import time

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.builders import (
    create_industry_context_service,
    create_industry_support_service,
    create_macro_context_service,
    create_macro_support_service,
    create_proposal_service,
    create_watchlist_orchestration_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.optimizations import WeightOptimizationService


def process_once() -> bool:
    session = SessionLocal()
    try:
        settings_repository = SettingsRepository(session)
        proposal_service = create_proposal_service(session)
        service = JobExecutionService(
            jobs=JobRepository(session),
            runs=RunRepository(session),
            evaluations=EvaluationExecutionService(
                recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
            ),
            optimizations=WeightOptimizationService(
                session=session,
                minimum_resolved_trades=settings_repository.get_optimization_minimum_resolved_trades(),
            ),
            macro_support=create_macro_support_service(session),
            industry_support=create_industry_support_service(session),
            macro_context=create_macro_context_service(session),
            industry_context=create_industry_context_service(session),
            watchlist_orchestration=create_watchlist_orchestration_service(session, proposal_service=proposal_service),
            recommendation_plans=RecommendationPlanRepository(session),
        )
        try:
            run, _recommendations = service.process_next_queued_run()
            return run is not None
        except Exception as exc:
            print(f"worker error: run processing failed: {exc}")
            traceback.print_exc()
            return True
    finally:
        session.close()


def main() -> None:
    print("worker started: processing queued runs")
    while True:
        processed = process_once()
        if not processed:
            time.sleep(2)


if __name__ == "__main__":
    main()
