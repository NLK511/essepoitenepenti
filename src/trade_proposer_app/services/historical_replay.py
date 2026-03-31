from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice, Run
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository


class HistoricalReplayService:
    def __init__(
        self,
        historical_replays: HistoricalReplayRepository,
        jobs: JobRepository,
        runs: RunRepository,
    ) -> None:
        self.historical_replays = historical_replays
        self.jobs = jobs
        self.runs = runs

    def create_batch(
        self,
        *,
        name: str,
        mode: str,
        as_of_start: datetime,
        as_of_end: datetime,
        cadence: str = "daily",
        config: dict[str, object] | None = None,
    ) -> HistoricalReplayBatch:
        normalized_start = self._normalize(as_of_start)
        normalized_end = self._normalize(as_of_end)
        if normalized_end < normalized_start:
            raise ValueError("as_of_end must be greater than or equal to as_of_start")
        if mode not in {"strict", "research"}:
            raise ValueError("mode must be either 'strict' or 'research'")
        if cadence != "daily":
            raise ValueError("only daily cadence is currently supported")

        batch = self.historical_replays.create_batch(
            name=name,
            mode=mode,
            as_of_start=normalized_start,
            as_of_end=normalized_end,
            cadence=cadence,
            config=config or {},
        )
        self.historical_replays.create_daily_slices(batch.id or 0)
        return self.historical_replays.refresh_batch_status(batch.id or 0)

    def enqueue_batch(self, batch_id: int) -> list[Run]:
        batch = self.historical_replays.get_batch(batch_id)
        slices = self.historical_replays.list_slices(batch_id)
        if not slices:
            raise ValueError("historical replay batch has no slices")
        system_job = self.jobs.get_or_create_system_job(f"historical_replay_batch_{batch_id}", JobType.HISTORICAL_REPLAY)
        self.historical_replays.update_batch_status(batch_id, status="queued", job_id=system_job.id)
        queued_runs: list[Run] = []
        for slice_row in slices:
            if slice_row.run_id is not None:
                continue
            run = self.runs.enqueue(
                system_job.id or 0,
                scheduled_for=slice_row.as_of,
                job_type=JobType.HISTORICAL_REPLAY,
            )
            self.runs.set_artifact(
                run.id or 0,
                {
                    "historical_replay": {
                        "batch_id": batch_id,
                        "slice_id": slice_row.id,
                        "as_of": slice_row.as_of.isoformat(),
                        "mode": batch.mode,
                        "cadence": batch.cadence,
                    }
                },
            )
            self.historical_replays.attach_slice_run(
                slice_row.id or 0,
                job_id=system_job.id or 0,
                run_id=run.id or 0,
                status="queued",
            )
            queued_runs.append(run)
        self.jobs.mark_enqueued(system_job.id or 0)
        self.historical_replays.refresh_batch_status(batch_id)
        return queued_runs

    def mark_slice_running(self, slice_id: int) -> HistoricalReplaySlice:
        return self.historical_replays.update_slice_status(slice_id, status="running")

    def complete_slice(
        self,
        slice_id: int,
        *,
        input_summary: dict[str, object],
        output_summary: dict[str, object],
        timing: dict[str, object],
    ) -> HistoricalReplaySlice:
        slice_row = self.historical_replays.update_slice_status(
            slice_id,
            status="completed",
            input_summary=input_summary,
            output_summary=output_summary,
            timing=timing,
            error_message="",
        )
        self.historical_replays.refresh_batch_status(slice_row.replay_batch_id)
        return slice_row

    def fail_slice(self, slice_id: int, *, error_message: str, timing: dict[str, object] | None = None) -> HistoricalReplaySlice:
        slice_row = self.historical_replays.update_slice_status(
            slice_id,
            status="failed",
            timing=timing,
            error_message=error_message,
        )
        self.historical_replays.refresh_batch_status(slice_row.replay_batch_id)
        return slice_row

    def build_stub_execution_payload(self, batch_id: int, slice_id: int) -> tuple[dict[str, object], dict[str, object]]:
        batch = self.historical_replays.get_batch(batch_id)
        slice_row = self.historical_replays.get_slice(slice_id)
        input_summary = {
            "as_of": slice_row.as_of.isoformat(),
            "mode": batch.mode,
            "cadence": batch.cadence,
            "status": "stub_execution",
        }
        output_summary = {
            "batch_id": batch.id,
            "slice_id": slice_row.id,
            "message": "Historical replay scaffolding run completed; replay generation pipeline not implemented yet.",
            "next_step": "connect market-data replay inputs and plan generation",
        }
        return input_summary, output_summary

    @staticmethod
    def default_batch_window(days: int = 30) -> tuple[datetime, datetime]:
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=max(0, days - 1))
        return start, end

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
