from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.bars_refresh import BarsRefreshService
from trade_proposer_app.services.builders import create_proposal_service, create_watchlist_orchestration_service
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService


def _historical_replay_service(session, *, hydrate_inputs: bool = False):
    return HistoricalReplayService(
        historical_replays=HistoricalReplayRepository(session),
        jobs=JobRepository(session),
        runs=RunRepository(session),
        historical_market_data=HistoricalMarketDataService(HistoricalMarketDataRepository(session)) if hydrate_inputs else None,
        historical_news=HistoricalNewsRepository(session),
        context_snapshots=ContextSnapshotRepository(session),
        fundamental_snapshots=FundamentalAnalysisSnapshotRepository(session),
    )


def _job_execution_service(session):
    proposal_service = create_proposal_service(session)
    historical_replay = _historical_replay_service(session, hydrate_inputs=False)
    return JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        evaluations=EvaluationExecutionService(
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        plan_generation_tuning=PlanGenerationTuningService(session),
        performance_assessment=PerformanceAssessmentService(session),
        watchlist_orchestration=create_watchlist_orchestration_service(session, proposal_service=proposal_service),
        recommendation_plans=RecommendationPlanRepository(session),
        historical_replay=historical_replay,
        bars_refresh=BarsRefreshService(HistoricalMarketDataRepository(session)),
    )


def _execute_run_fresh_session(run_id: int, label: str) -> dict[str, object]:
    session = SessionLocal()
    try:
        executor = _job_execution_service(session)
        executor.execute_run(run_id, worker_id="aurelio-replay-experiment")
        session.commit()
        return {"label": label, "run_id": run_id, "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"label": label, "run_id": run_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()


def _execute_runs(queued, *, label: str, executor, max_workers: int) -> None:
    if max_workers <= 1:
        for run in queued:
            try:
                executor.execute_run(run.id or 0, worker_id="aurelio-replay-experiment")
                print({"label": label, "run_id": run.id, "status": "completed"})
            except Exception as exc:  # noqa: BLE001
                print({"label": label, "run_id": run.id, "status": "failed", "error": str(exc)})
        return
    run_ids = [run.id or 0 for run in queued]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_execute_run_fresh_session, run_id, label) for run_id in run_ids]
        for future in as_completed(futures):
            print(future.result())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run actionability-floor replay batches. Defaults to safe sequential execution.")
    parser.add_argument("--max-workers", type=int, default=1, help="Future parallel execution hook; keep at 1 on constrained hosts or provider-limited runs.")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        tuning = PlanGenerationTuningService(session)
        active = tuning._resolve_active_config_version()  # noqa: SLF001
        config_50 = dict(active.config)
        config_50["global.actionable_confidence_floor_percent"] = 50.0
        config_old = dict(active.config)
        config_old["global.actionable_confidence_floor_percent"] = 53.75
        service = _historical_replay_service(session, hydrate_inputs=False)
        executor = _job_execution_service(session)
        # Use the latest fully resolvable four-week window. The immediately
        # preceding week may still produce pending 5-day replay outcomes.
        end = datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc)
        start = end - timedelta(days=27)
        experiments = [
            ("floor_53_75_baseline", config_old),
            ("floor_50_candidate", config_50),
        ]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for label, config in experiments:
            batch = service.create_batch(
                name=f"actionability-floor-replay-{label}-{stamp}",
                mode="research",
                as_of_start=start,
                as_of_end=end,
                cadence="daily",
                universe_preset="us_large_cap_top20_v1",
                entry_timing="next_open",
                price_provider="yahoo",
                config={
                    "created_via": "script",
                    "experiment": "actionability_floor_50_vs_53_75",
                    "label": label,
                    "plan_generation_tuning_config_override": config,
                },
            )
            queued = service.enqueue_batch(batch.id or 0)
            print({"label": label, "batch_id": batch.id, "queued_runs": [r.id for r in queued]})
            _execute_runs(queued, label=label, executor=executor, max_workers=args.max_workers)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
