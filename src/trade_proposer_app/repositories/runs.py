import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.domain.models import Run, WorkerHeartbeat
from trade_proposer_app.persistence.models import (
    IndustryContextSnapshotRecord,
    JobRecord,
    MacroContextSnapshotRecord,
    RecommendationDecisionSampleRecord,
    RecommendationOutcomeRecord,
    RecommendationPlanRecord,
    RunRecord,
    SupportSnapshotRecord,
    TickerSignalSnapshotRecord,
    WorkerHeartbeatRecord,
)


ACTIVE_RUN_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
TERMINAL_RUN_STATUSES = (
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_WARNINGS.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELED.value,
)


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        job_id: int,
        status: str,
        error_message: str | None = None,
        scheduled_for: datetime | None = None,
        job_type: JobType | None = None,
    ) -> Run:
        resolved_job_type = self._resolve_job_type(job_id, job_type)
        record = RunRecord(
            job_id=job_id,
            job_type=resolved_job_type.value,
            status=status,
            error_message=error_message or "",
            scheduled_for=self._normalize_optional_datetime(scheduled_for),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def enqueue(
        self,
        job_id: int,
        scheduled_for: datetime | None = None,
        job_type: JobType | None = None,
    ) -> Run:
        return self.create(
            job_id=job_id,
            status=RunStatus.QUEUED.value,
            scheduled_for=scheduled_for,
            job_type=job_type,
        )

    def get_run(self, run_id: int) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        return self._to_run_model(record)

    def get_active_run_for_job(self, job_id: int) -> Run | None:
        record = self.session.scalars(
            select(RunRecord)
            .where(RunRecord.job_id == job_id)
            .where(RunRecord.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        ).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def get_run_for_job_and_scheduled_for(self, job_id: int, scheduled_for: datetime) -> Run | None:
        record = self.session.scalars(
            select(RunRecord)
            .where(RunRecord.job_id == job_id)
            .where(RunRecord.scheduled_for == self._normalize_datetime(scheduled_for))
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        ).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def get_active_run_for_job_type(self, job_type: JobType, exclude_run_id: int | None = None) -> Run | None:
        query = (
            select(RunRecord)
            .where(RunRecord.job_type == job_type.value)
            .where(RunRecord.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        )
        if exclude_run_id is not None:
            query = query.where(RunRecord.id != exclude_run_id)
        record = self.session.scalars(query).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def claim_next_queued_run(self, worker_id: str | None = None, lease_seconds: int = 300) -> Run | None:
        while True:
            candidate_id = self.session.scalars(
                select(RunRecord.id)
                .where(RunRecord.status == RunStatus.QUEUED.value)
                .order_by(RunRecord.created_at.asc())
                .limit(1)
            ).first()
            if candidate_id is None:
                return None

            claimed = self.claim_queued_run(candidate_id, worker_id=worker_id, lease_seconds=lease_seconds)
            if claimed is not None:
                return claimed

    def recover_stale_running_runs(
        self,
        *,
        stale_after_seconds: int,
        now: datetime | None = None,
    ) -> list[Run]:
        if stale_after_seconds <= 0:
            return []
        reference_now = self._normalize_optional_datetime(now) or datetime.now(timezone.utc)
        stale_before = reference_now - timedelta(seconds=stale_after_seconds)

        # Recover based on lease expiration
        lease_stale_records = list(
            self.session.scalars(
                select(RunRecord)
                .where(RunRecord.status == RunStatus.RUNNING.value)
                .where(RunRecord.lease_expires_at.is_not(None))
                .where(RunRecord.lease_expires_at < reference_now)
            ).all()
        )

        # Recover based on legacy started_at timeout (for runs without leases)
        started_at_stale_records = list(
            self.session.scalars(
                select(RunRecord)
                .where(RunRecord.status == RunStatus.RUNNING.value)
                .where(RunRecord.lease_expires_at.is_(None))
                .where(RunRecord.started_at.is_not(None))
                .where(RunRecord.completed_at.is_(None))
                .where(RunRecord.started_at < stale_before)
                .order_by(RunRecord.started_at.asc())
            ).all()
        )

        stale_records = list({r.id: r for r in (lease_stale_records + started_at_stale_records)}.values())
        recovered: list[Run] = []
        for record in stale_records:
            timing = self._deserialize_json_object(record.timing_json)
            strategy = "lease_timeout" if record.lease_expires_at else "started_at_timeout"
            timing["recovery"] = {
                "recovered_at": reference_now.isoformat(),
                "strategy": strategy,
                "stale_after_seconds": stale_after_seconds,
                "previous_status": record.status,
            }
            record.status = RunStatus.FAILED.value
            previous_error = (record.error_message or "").strip()
            timeout_error = (
                f"Recovered stale running run via {strategy}."
            )
            record.error_message = f"{previous_error} | {timeout_error}" if previous_error else timeout_error
            record.timing_json = self._serialize_timing(timing)
            record.completed_at = reference_now
            started_at = self._normalize_optional_datetime(record.started_at)
            record.duration_seconds = (
                max(0.0, (reference_now - started_at).total_seconds()) if started_at is not None else None
            )
            recovered.append(self._to_run_model(record))
        if stale_records:
            self.session.commit()
            recovered = [self._to_run_model(record) for record in stale_records]
        return recovered

    def claim_queued_run(self, run_id: int, worker_id: str | None = None, lease_seconds: int = 300) -> Run | None:
        started_at = datetime.now(timezone.utc)
        lease_expires_at = started_at + timedelta(seconds=lease_seconds)
        result = self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .where(RunRecord.status == RunStatus.QUEUED.value)
            .values(
                status=RunStatus.RUNNING.value,
                error_message="",
                started_at=self._normalize_datetime(started_at),
                completed_at=None,
                duration_seconds=None,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
            )
        )
        self.session.commit()
        if result.rowcount != 1:
            return None
        record = self.session.get(RunRecord, run_id)
        if record is None:
            return None
        return self._to_run_model(record)

    def renew_lease(self, run_id: int, lease_seconds: int = 300) -> bool:
        new_expiry = self._normalize_datetime(datetime.now(timezone.utc)) + timedelta(seconds=lease_seconds)
        result = self.session.execute(
            update(RunRecord)
            .where(RunRecord.id == run_id)
            .where(RunRecord.status == RunStatus.RUNNING.value)
            .values(lease_expires_at=new_expiry)
        )
        self.session.commit()
        return result.rowcount == 1

    def update_status(
        self,
        run_id: int,
        status: str,
        error_message: str | None = None,
        timing: dict[str, object] | None = None,
    ) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.status = status
        record.error_message = error_message or ""
        if timing is not None:
            record.timing_json = self._serialize_timing(timing)
        if status in TERMINAL_RUN_STATUSES:
            record.completed_at = self._normalize_datetime(datetime.now(timezone.utc))
            record.lease_expires_at = None
            if record.started_at is not None:
                completed_at = self._normalize_datetime(record.completed_at)
                started_at = self._normalize_datetime(record.started_at)
                record.duration_seconds = max(0.0, (completed_at - started_at).total_seconds())
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def list_latest_runs(self, limit: int = 20) -> list[Run]:
        rows = self.session.scalars(select(RunRecord).order_by(RunRecord.created_at.desc()).limit(limit)).all()
        return [self._to_run_model(row) for row in rows]

    def list_runs_for_job_type(
        self,
        job_type: JobType,
        *,
        limit: int = 20,
        statuses: list[str] | None = None,
    ) -> list[Run]:
        query = select(RunRecord).where(RunRecord.job_type == job_type.value)
        if statuses:
            query = query.where(RunRecord.status.in_(statuses))
        rows = self.session.scalars(query.order_by(RunRecord.created_at.desc()).limit(limit)).all()
        return [self._to_run_model(row) for row in rows]

    def count_runs_for_job_type(self, job_type: JobType, *, statuses: list[str] | None = None) -> int:
        query = select(func.count()).select_from(RunRecord).where(RunRecord.job_type == job_type.value)
        if statuses:
            query = query.where(RunRecord.status.in_(statuses))
        return int(self.session.scalar(query) or 0)

    def list_latest_runs_above_confidence_threshold(self, confidence_threshold: float, limit: int = 20) -> list[Run]:
        rows = self.session.scalars(select(RunRecord).order_by(RunRecord.created_at.desc())).all()
        filtered: list[Run] = []
        for row in rows:
            has_confident_plan = self.session.scalars(
                select(RecommendationPlanRecord.id)
                .where(RecommendationPlanRecord.run_id == row.id)
                .where(RecommendationPlanRecord.confidence_percent >= confidence_threshold)
                .limit(1)
            ).first()
            if has_confident_plan is not None:
                filtered.append(self._to_run_model(row))
            if len(filtered) >= limit:
                break
        return filtered

    def set_timing(self, run_id: int, timing: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.timing_json = self._serialize_timing(timing)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def set_summary(self, run_id: int, summary: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.summary_json = self._serialize_timing(summary)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def set_artifact(self, run_id: int, artifact: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.artifact_json = self._serialize_timing(artifact)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def upsert_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        record = self.session.get(WorkerHeartbeatRecord, heartbeat.worker_id)
        now = datetime.now(timezone.utc)
        if record is None:
            record = WorkerHeartbeatRecord(
                worker_id=heartbeat.worker_id,
                hostname=heartbeat.hostname,
                pid=heartbeat.pid,
                status=heartbeat.status,
                last_heartbeat_at=self._normalize_datetime(now),
                started_at=self._normalize_optional_datetime(heartbeat.started_at) or self._normalize_datetime(now),
                version=heartbeat.version,
                active_run_id=heartbeat.active_run_id,
                metadata_json=heartbeat.metadata_json,
            )
            self.session.add(record)
        else:
            record.status = heartbeat.status
            record.last_heartbeat_at = self._normalize_datetime(now)
            if record.started_at is not None:
                record.started_at = self._normalize_datetime(record.started_at)
            record.active_run_id = heartbeat.active_run_id
            record.metadata_json = heartbeat.metadata_json
            if heartbeat.version:
                record.version = heartbeat.version
        self.session.commit()

    def list_active_workers(self, stale_seconds: int = 60) -> list[WorkerHeartbeat]:
        stale_before = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        rows = self.session.scalars(
            select(WorkerHeartbeatRecord)
            .where(WorkerHeartbeatRecord.last_heartbeat_at >= stale_before)
            .order_by(WorkerHeartbeatRecord.last_heartbeat_at.desc())
        ).all()
        return [self._to_heartbeat_model(row) for row in rows]

    def delete_run(self, run_id: int) -> None:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        plan_ids = list(
            self.session.scalars(
                select(RecommendationPlanRecord.id).where(RecommendationPlanRecord.run_id == run_id)
            ).all()
        )
        if plan_ids:
            self.session.execute(
                delete(RecommendationDecisionSampleRecord).where(
                    RecommendationDecisionSampleRecord.recommendation_plan_id.in_(plan_ids)
                )
            )
            self.session.execute(
                delete(RecommendationOutcomeRecord).where(RecommendationOutcomeRecord.recommendation_plan_id.in_(plan_ids))
            )
            self.session.execute(delete(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_(plan_ids)))
        self.session.execute(delete(TickerSignalSnapshotRecord).where(TickerSignalSnapshotRecord.run_id == run_id))
        self.session.execute(delete(MacroContextSnapshotRecord).where(MacroContextSnapshotRecord.run_id == run_id))
        self.session.execute(delete(IndustryContextSnapshotRecord).where(IndustryContextSnapshotRecord.run_id == run_id))
        self.session.execute(delete(SupportSnapshotRecord).where(SupportSnapshotRecord.run_id == run_id))
        self.session.delete(record)
        self.session.commit()

    def _to_run_model(self, record: RunRecord) -> Run:
        return Run(
            id=record.id,
            job_id=record.job_id,
            job_type=JobType(record.job_type or JobType.PROPOSAL_GENERATION.value),
            status=record.status,
            error_message=record.error_message or None,
            scheduled_for=self._normalize_optional_datetime(record.scheduled_for),
            summary_json=record.summary_json or None,
            artifact_json=record.artifact_json or None,
            created_at=self._normalize_datetime(record.created_at),
            updated_at=self._normalize_datetime(record.updated_at),
            started_at=self._normalize_optional_datetime(record.started_at),
            completed_at=self._normalize_optional_datetime(record.completed_at),
            duration_seconds=record.duration_seconds,
            worker_id=record.worker_id,
            lease_expires_at=self._normalize_optional_datetime(record.lease_expires_at),
            timing_json=record.timing_json or None,
        )

    def _to_heartbeat_model(self, record: WorkerHeartbeatRecord) -> WorkerHeartbeat:
        return WorkerHeartbeat(
            worker_id=record.worker_id,
            hostname=record.hostname,
            pid=record.pid,
            status=record.status,
            last_heartbeat_at=self._normalize_datetime(record.last_heartbeat_at),
            started_at=self._normalize_datetime(record.started_at),
            version=record.version,
            active_run_id=record.active_run_id,
            metadata_json=record.metadata_json,
            created_at=self._normalize_datetime(record.created_at),
            updated_at=self._normalize_datetime(record.updated_at),
        )

    def _resolve_job_type(self, job_id: int, job_type: JobType | None) -> JobType:
        if job_type is not None:
            return job_type
        job = self.session.get(JobRecord, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return JobType(job.job_type or JobType.PROPOSAL_GENERATION.value)

    @staticmethod
    def _serialize_timing(timing: dict[str, object]) -> str:
        return json.dumps(timing, indent=2, sort_keys=True)

    @staticmethod
    def _deserialize_json_object(payload: str | None) -> dict[str, object]:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _normalize_optional_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._normalize_datetime(value)
