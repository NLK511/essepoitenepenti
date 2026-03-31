import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import EvaluationRunResult, Recommendation, RunDiagnostics, RunOutput
from trade_proposer_app.persistence.models import Base, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.runs import enqueue_enabled_jobs
from trade_proposer_app.workers.tasks import process_once


class StubProposalService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def generate(self, ticker: str) -> RunOutput:
        return RunOutput(
            recommendation=Recommendation(
                ticker=ticker,
                direction=RecommendationDirection.LONG,
                confidence=72.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                indicator_summary="Above SMA200 · RSI 55.0",
            ),
            diagnostics=RunDiagnostics(
                warnings=["news degraded"],
                provider_errors=["feed timeout"],
                raw_output="raw output",
                analysis_json='{"problems": ["news degraded"]}',
            ),
        )


class FailingProposalService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def generate(self, ticker: str) -> RunOutput:
        raise RuntimeError(f"dependency missing for {ticker}")


class StubEvaluationExecutionService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def execute(self, run=None) -> EvaluationRunResult:
        return EvaluationRunResult(
            evaluated_recommendation_plans=8,
            synced_recommendation_plan_outcomes=3,
            pending_recommendation_plan_outcomes=2,
            win_recommendation_plan_outcomes=3,
            loss_recommendation_plan_outcomes=1,
            output="scheduled evaluation complete",
        )


class StubOptimizationService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def execute(self) -> tuple[dict[str, object], dict[str, object]]:
        return (
            {
                "status": "completed",
                "resolved_trade_count": 99,
                "minimum_resolved_trades": 50,
                "weights_changed": True,
                "stdout": "scheduled optimization complete",
                "stderr": "",
            },
            {
                "weights_path": "/tmp/weights.json",
                "before": {"exists": True, "sha256": "abc"},
                "after": {"exists": True, "sha256": "def"},
            },
        )


class StubMacroSupportRefreshService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def refresh(self, *, job_id: int | None = None, run_id: int | None = None) -> Any:
        return type(
            "Snapshot",
            (),
            {
                "id": 11,
                "subject_key": "global_macro",
                "subject_label": "Global Macro",
                "score": 0.1,
                "label": "NEUTRAL",
                "computed_at": datetime(2026, 3, 22, 6, 0, 0, tzinfo=timezone.utc),
            },
        )()


class StubIndustrySupportRefreshService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def refresh_all(self, *, job_id: int | None = None, run_id: int | None = None) -> list[Any]:
        return [
            type(
                "Snapshot",
                (),
                {
                    "id": 21,
                    "subject_key": "consumer_electronics",
                    "subject_label": "Consumer Electronics",
                    "score": 0.12,
                    "label": "POSITIVE",
                },
            )()
        ]


class WorkerSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)

    def create_session(self) -> Session:
        return Session(bind=self.engine)

    def test_scheduler_enqueues_only_scheduled_jobs_without_duplicate_active_runs(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)

        scheduled = jobs.create("Scheduled", ["AAPL"], "0 * * * *")
        jobs.create("Manual", ["MSFT"], None)
        already_active = jobs.create("Already Active", ["NVDA"], "*/5 * * * *")
        runs.enqueue(already_active.id or 0)

        scheduled_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            count = enqueue_enabled_jobs(now=scheduled_now)

        self.assertEqual(count, 1)
        all_runs = runs.list_latest_runs(limit=10)
        self.assertEqual(len(all_runs), 2)
        scheduled_runs = [run for run in all_runs if run.job_id == scheduled.id]
        active_runs = [run for run in all_runs if run.job_id == already_active.id]
        self.assertEqual(len(scheduled_runs), 1)
        self.assertEqual(len(active_runs), 1)
        self.assertEqual(scheduled_runs[0].scheduled_for, scheduled_now)

    def test_scheduler_does_not_reenqueue_same_schedule_slot(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        scheduled = jobs.create("Scheduled", ["AAPL"], "0 * * * *")
        scheduled_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            first_count = enqueue_enabled_jobs(now=scheduled_now)
            second_count = enqueue_enabled_jobs(now=scheduled_now)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        all_runs = [run for run in runs.list_latest_runs(limit=10) if run.job_id == scheduled.id]
        self.assertEqual(len(all_runs), 1)
        self.assertEqual(all_runs[0].scheduled_for, scheduled_now)

    def test_scheduler_skips_jobs_not_due_at_current_slot(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        jobs.create("Scheduled", ["AAPL"], "0 * * * *")
        not_due_now = datetime(2026, 3, 14, 10, 17, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            count = enqueue_enabled_jobs(now=not_due_now)

        self.assertEqual(count, 0)
        scheduled_runs = [item for item in runs.list_latest_runs(limit=10) if item.job_id is not None and item.scheduled_for is not None]
        self.assertEqual(len(scheduled_runs), 0)

    def test_scheduler_enqueues_non_proposal_jobs_with_job_type_metadata(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        evaluation = jobs.create(
            "Scheduled Evaluation",
            [],
            "0 18 * * *",
            job_type=JobType.RECOMMENDATION_EVALUATION,
        )
        optimization = jobs.create(
            "Scheduled Optimization",
            [],
            "0 2 * * 0",
            job_type=JobType.WEIGHT_OPTIMIZATION,
        )
        scheduled_eval = datetime(2026, 3, 14, 18, 0, tzinfo=timezone.utc)
        scheduled_opt = datetime(2026, 3, 15, 2, 0, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            eval_count = enqueue_enabled_jobs(now=scheduled_eval)
            opt_count = enqueue_enabled_jobs(now=scheduled_opt)

        self.assertEqual(eval_count, 1)
        self.assertEqual(opt_count, 1)
        evaluation_run = next(run for run in runs.list_latest_runs(limit=10) if run.job_id == evaluation.id)
        optimization_run = next(run for run in runs.list_latest_runs(limit=10) if run.job_id == optimization.id)
        self.assertEqual(evaluation_run.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertEqual(optimization_run.job_type, JobType.WEIGHT_OPTIMIZATION)
        self.assertEqual(evaluation_run.scheduled_for, scheduled_eval)
        self.assertEqual(optimization_run.scheduled_for, scheduled_opt)

    def test_scheduler_uses_watchlist_optimized_timing_when_job_has_no_manual_schedule(self) -> None:
        session = self.create_session()
        watchlists = WatchlistRepository(session)
        jobs = JobRepository(session)
        runs = RunRepository(session)
        watchlist = watchlists.create(
            "US Swing",
            ["AAPL", "MSFT"],
            timezone="America/New_York",
            default_horizon=StrategyHorizon.ONE_DAY,
            optimize_evaluation_timing=True,
        )
        scheduled = jobs.create("Optimized US Swing", [], None, watchlist_id=watchlist.id)
        scheduled_now = datetime(2026, 3, 16, 13, 20, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            count = enqueue_enabled_jobs(now=scheduled_now)

        self.assertEqual(count, 1)
        scheduled_runs = [run for run in runs.list_latest_runs(limit=10) if run.job_id == scheduled.id]
        self.assertEqual(len(scheduled_runs), 1)
        self.assertEqual(scheduled_runs[0].scheduled_for, scheduled_now)

    def test_scheduler_skips_watchlist_optimized_job_when_timezone_is_missing(self) -> None:
        session = self.create_session()
        watchlists = WatchlistRepository(session)
        jobs = JobRepository(session)
        runs = RunRepository(session)
        watchlist = watchlists.create(
            "Broken Optimized",
            ["AAPL"],
            timezone="",
            default_horizon=StrategyHorizon.ONE_DAY,
            optimize_evaluation_timing=True,
        )
        jobs.create("Broken Job", [], None, watchlist_id=watchlist.id)
        scheduled_now = datetime(2026, 3, 16, 13, 20, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            count = enqueue_enabled_jobs(now=scheduled_now)

        self.assertEqual(count, 0)
        self.assertEqual(runs.list_latest_runs(limit=10), [])

    def test_run_claim_only_succeeds_once(self) -> None:
        jobs_session = self.create_session()
        try:
            job = JobRepository(jobs_session).create("Claim Once", ["TSLA"], None)
            RunRepository(jobs_session).enqueue(job.id or 0)
        finally:
            jobs_session.close()

        first_session = self.create_session()
        second_session = self.create_session()
        try:
            first_claim = RunRepository(first_session).claim_next_queued_run()
            second_claim = RunRepository(second_session).claim_next_queued_run()
        finally:
            first_session.close()
            second_session.close()

        self.assertIsNotNone(first_claim)
        self.assertIsNone(second_claim)

    def test_scheduler_recovers_stale_running_run_before_enqueuing_next_slot(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Recover Scheduled Slot", ["AAPL"], "0 * * * *")
        stale_run = runs.enqueue(job.id or 0)
        # Manually set to RUNNING without lease
        session.execute(
            update(RunRecord)
            .where(RunRecord.id == stale_run.id)
            .values(status="running", started_at=datetime(2026, 3, 14, 8, 0, tzinfo=timezone.utc))
        )
        session.commit()
        
        scheduled_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        previous_timeout = settings.run_stale_after_seconds
        settings.run_stale_after_seconds = 300
        try:
            with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
                count = enqueue_enabled_jobs(now=scheduled_now)
        finally:
            settings.run_stale_after_seconds = previous_timeout

        self.assertEqual(count, 1)
        self.assertEqual(runs.get_run(stale_run.id or 0).status, "failed")
        scheduled_runs = [run for run in runs.list_latest_runs(limit=10) if run.job_id == job.id and run.id != stale_run.id]
        self.assertEqual(len(scheduled_runs), 1)
        self.assertEqual(scheduled_runs[0].scheduled_for, scheduled_now)

    def test_worker_process_once_processes_queued_run(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Worker Job", ["TSLA"], None)
        runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.list_latest_runs(limit=1)[0]
        self.assertEqual(updated_run.status, "completed_with_warnings")
        self.assertIsNotNone(updated_run.duration_seconds)
        self.assertIsNotNone(updated_run.timing_json)
        assert updated_run.timing_json is not None
        self.assertIn('"ticker_generation"', updated_run.timing_json)

    def test_worker_process_once_processes_evaluation_run(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Evaluation Job",
            [],
            None,
            job_type=JobType.RECOMMENDATION_EVALUATION,
        )
        run = runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ), patch(
            "trade_proposer_app.workers.tasks.EvaluationExecutionService", StubEvaluationExecutionService
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.get_run(run.id or 0)
        self.assertEqual(updated_run.status, "completed")
        self.assertEqual(updated_run.job_type, JobType.RECOMMENDATION_EVALUATION)
        self.assertIn('"synced_recommendation_plan_outcomes": 3', updated_run.summary_json or "")
        self.assertIn('"evaluation_seconds"', updated_run.timing_json or "")

    def test_worker_process_once_processes_optimization_run(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Optimization Job",
            [],
            None,
            job_type=JobType.WEIGHT_OPTIMIZATION,
        )
        run = runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ), patch(
            "trade_proposer_app.workers.tasks.WeightOptimizationService", StubOptimizationService
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.get_run(run.id or 0)
        self.assertEqual(updated_run.status, "completed")
        self.assertEqual(updated_run.job_type, JobType.WEIGHT_OPTIMIZATION)
        self.assertIn('"weights_changed": true', (updated_run.summary_json or "").lower())
        self.assertIn('"weights_path": "/tmp/weights.json"', updated_run.artifact_json or "")
        self.assertIn('"optimization_seconds"', updated_run.timing_json or "")

    def test_worker_process_once_processes_macro_support_refresh_run(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Macro Refresh Job",
            [],
            None,
            job_type=JobType.MACRO_SENTIMENT_REFRESH,
        )
        run = runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ), patch(
            "trade_proposer_app.workers.tasks.create_macro_support_service", return_value=StubMacroSupportRefreshService()
        ), patch(
            "trade_proposer_app.workers.tasks.create_industry_support_service", return_value=StubIndustrySupportRefreshService()
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.get_run(run.id or 0)
        self.assertEqual(updated_run.status, "completed")
        self.assertEqual(updated_run.job_type, JobType.MACRO_SENTIMENT_REFRESH)
        self.assertIn('"scope": "macro"', updated_run.summary_json or "")
        self.assertIn('"snapshot_id": 11', updated_run.artifact_json or "")
        self.assertIn('"macro_refresh_seconds"', updated_run.timing_json or "")

    def test_worker_process_once_processes_industry_support_refresh_run(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create(
            "Industry Refresh Job",
            [],
            None,
            job_type=JobType.INDUSTRY_SENTIMENT_REFRESH,
        )
        run = runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ), patch(
            "trade_proposer_app.workers.tasks.create_macro_support_service", return_value=StubMacroSupportRefreshService()
        ), patch(
            "trade_proposer_app.workers.tasks.create_industry_support_service", return_value=StubIndustrySupportRefreshService()
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.get_run(run.id or 0)
        self.assertEqual(updated_run.status, "completed")
        self.assertEqual(updated_run.job_type, JobType.INDUSTRY_SENTIMENT_REFRESH)
        self.assertIn('"scope": "industry"', updated_run.summary_json or "")
        self.assertIn('"snapshot_count": 1', updated_run.artifact_json or "")
        self.assertIn('"industry_refresh_seconds"', updated_run.timing_json or "")

    def test_scheduler_skips_second_optimization_job_when_one_is_active(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        first = jobs.create("Optimization One", [], "0 2 * * *", job_type=JobType.WEIGHT_OPTIMIZATION)
        second = jobs.create("Optimization Two", [], "0 2 * * *", job_type=JobType.WEIGHT_OPTIMIZATION)
        runs.enqueue(first.id or 0)
        scheduled_now = datetime(2026, 3, 15, 2, 0, tzinfo=timezone.utc)

        with patch("trade_proposer_app.services.runs.SessionLocal", return_value=session):
            count = enqueue_enabled_jobs(now=scheduled_now)

        self.assertEqual(count, 0)
        optimization_runs = [run for run in runs.list_latest_runs(limit=10) if run.job_type == JobType.WEIGHT_OPTIMIZATION]
        self.assertEqual(len(optimization_runs), 1)
        self.assertEqual(optimization_runs[0].job_id, first.id)
        self.assertNotEqual(first.id, second.id)

    def test_worker_process_once_marks_run_failed_without_crashing_worker(self) -> None:
        session = self.create_session()
        jobs = JobRepository(session)
        runs = RunRepository(session)
        job = jobs.create("Broken Job", ["TSLA"], None)
        run = runs.enqueue(job.id or 0)

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=FailingProposalService()
        ):
            processed = process_once()

        self.assertTrue(processed)
        updated_run = runs.get_run(run.id or 0)
        self.assertEqual(updated_run.status, "completed_with_warnings")
        self.assertIsNone(updated_run.error_message)
        self.assertIsNotNone(updated_run.duration_seconds)
        self.assertIsNotNone(updated_run.timing_json)
        assert updated_run.timing_json is not None
        self.assertIn('"recommendation_generation_seconds"', updated_run.timing_json)

    def test_worker_process_once_returns_false_when_queue_empty(self) -> None:
        session = self.create_session()

        with patch("trade_proposer_app.workers.tasks.SessionLocal", return_value=session), patch(
            "trade_proposer_app.workers.tasks.create_proposal_service", return_value=StubProposalService()
        ):
            processed = process_once()

        self.assertFalse(processed)


if __name__ == "__main__":
    unittest.main()
