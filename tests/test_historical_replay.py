import json
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.job_execution import JobExecutionService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class HistoricalReplayTests(unittest.TestCase):
    def test_create_batch_creates_daily_slices(self) -> None:
        session = create_session()
        try:
            service = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
            )
            batch = service.create_batch(
                name="Replay MVP",
                mode="research",
                as_of_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 1, 3, tzinfo=timezone.utc),
            )
            repository = HistoricalReplayRepository(session)
            slices = repository.list_slices(batch.id or 0)
            self.assertEqual(3, len(slices))
            self.assertEqual(["planned", "planned", "planned"], [item.status for item in slices])
            summary = repository.summarize_batch(batch.id or 0)
            self.assertEqual(3, summary["slice_count"])
            self.assertEqual(3, summary["planned_count"])
        finally:
            session.close()

    def test_enqueue_and_execute_single_slice_run(self) -> None:
        session = create_session()
        try:
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
            )
            batch = historical_replay.create_batch(
                name="Replay single day",
                mode="strict",
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 2, 5, tzinfo=timezone.utc),
            )
            queued_runs = historical_replay.enqueue_batch(batch.id or 0)
            self.assertEqual(1, len(queued_runs))
            queued_run = queued_runs[0]
            self.assertEqual(JobType.HISTORICAL_REPLAY, queued_run.job_type)

            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None
            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")
            self.assertEqual(RunStatus.COMPLETED, final_run.status)
            summary = json.loads(final_run.summary_json or "{}")
            self.assertEqual(batch.id, summary["replay_batch_id"])
            self.assertEqual("strict", summary["mode"])

            repository = HistoricalReplayRepository(session)
            refreshed_batch = repository.get_batch(batch.id or 0)
            self.assertEqual("completed", refreshed_batch.status)
            slice_row = repository.list_slices(batch.id or 0)[0]
            self.assertEqual("completed", slice_row.status)
            output_summary = json.loads(slice_row.output_summary_json)
            self.assertIn("Historical replay scaffolding run completed", output_summary["message"])
        finally:
            session.close()
