from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import (
    PlanGenerationTuningCandidate,
    PlanGenerationTuningConfigVersion,
    PlanGenerationTuningEvent,
    PlanGenerationTuningRun,
)
from trade_proposer_app.persistence.models import (
    PlanGenerationTuningCandidateRecord,
    PlanGenerationTuningConfigVersionRecord,
    PlanGenerationTuningEventRecord,
    PlanGenerationTuningRunRecord,
)


class PlanGenerationTuningRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, run: PlanGenerationTuningRun) -> PlanGenerationTuningRun:
        record = PlanGenerationTuningRunRecord()
        self._apply_run(record, run)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self.get_run(record.id)

    def update_run(self, run_id: int, run: PlanGenerationTuningRun) -> PlanGenerationTuningRun:
        record = self.session.get(PlanGenerationTuningRunRecord, run_id)
        if record is None:
            raise ValueError(f"plan generation tuning run {run_id} not found")
        self._apply_run(record, run)
        self.session.commit()
        self.session.refresh(record)
        return self.get_run(record.id)

    def get_run(self, run_id: int) -> PlanGenerationTuningRun:
        record = self.session.get(PlanGenerationTuningRunRecord, run_id)
        if record is None:
            raise ValueError(f"plan generation tuning run {run_id} not found")
        return self._to_run_model(record)

    def list_runs(self, *, limit: int = 20, offset: int = 0) -> list[PlanGenerationTuningRun]:
        rows = self.session.scalars(
            select(PlanGenerationTuningRunRecord)
            .order_by(desc(PlanGenerationTuningRunRecord.created_at), desc(PlanGenerationTuningRunRecord.id))
            .offset(max(0, offset))
            .limit(max(1, limit))
        ).all()
        return [self._to_run_model(row) for row in rows]

    def count_runs(self) -> int:
        return len(self.session.scalars(select(PlanGenerationTuningRunRecord.id)).all())

    def get_latest_run(self) -> PlanGenerationTuningRun | None:
        row = self.session.scalar(
            select(PlanGenerationTuningRunRecord)
            .order_by(desc(PlanGenerationTuningRunRecord.created_at), desc(PlanGenerationTuningRunRecord.id))
            .limit(1)
        )
        return self._to_run_model(row) if row is not None else None

    def create_candidate(self, candidate: PlanGenerationTuningCandidate) -> PlanGenerationTuningCandidate:
        record = PlanGenerationTuningCandidateRecord(run_id=candidate.run_id or 0)
        self._apply_candidate(record, candidate)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_candidate_model(record)

    def list_candidates_for_run(self, run_id: int) -> list[PlanGenerationTuningCandidate]:
        rows = self.session.scalars(
            select(PlanGenerationTuningCandidateRecord)
            .where(PlanGenerationTuningCandidateRecord.run_id == run_id)
            .order_by(PlanGenerationTuningCandidateRecord.rank.asc(), PlanGenerationTuningCandidateRecord.id.asc())
        ).all()
        return [self._to_candidate_model(row) for row in rows]

    def create_config_version(self, version: PlanGenerationTuningConfigVersion) -> PlanGenerationTuningConfigVersion:
        record = PlanGenerationTuningConfigVersionRecord()
        self._apply_config_version(record, version)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_config_version_model(record)

    def get_config_version(self, config_version_id: int) -> PlanGenerationTuningConfigVersion:
        record = self.session.get(PlanGenerationTuningConfigVersionRecord, config_version_id)
        if record is None:
            raise ValueError(f"plan generation tuning config version {config_version_id} not found")
        return self._to_config_version_model(record)

    def list_config_versions(self, *, limit: int = 20, offset: int = 0) -> list[PlanGenerationTuningConfigVersion]:
        rows = self.session.scalars(
            select(PlanGenerationTuningConfigVersionRecord)
            .order_by(desc(PlanGenerationTuningConfigVersionRecord.created_at), desc(PlanGenerationTuningConfigVersionRecord.id))
            .offset(max(0, offset))
            .limit(max(1, limit))
        ).all()
        return [self._to_config_version_model(row) for row in rows]

    def count_config_versions(self) -> int:
        return len(self.session.scalars(select(PlanGenerationTuningConfigVersionRecord.id)).all())

    def create_event(self, event: PlanGenerationTuningEvent) -> PlanGenerationTuningEvent:
        record = PlanGenerationTuningEventRecord()
        self._apply_event(record, event)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_event_model(record)

    def list_events(self, *, run_id: int | None = None, config_version_id: int | None = None, limit: int = 50) -> list[PlanGenerationTuningEvent]:
        query = select(PlanGenerationTuningEventRecord)
        if run_id is not None:
            query = query.where(PlanGenerationTuningEventRecord.run_id == run_id)
        if config_version_id is not None:
            query = query.where(PlanGenerationTuningEventRecord.config_version_id == config_version_id)
        rows = self.session.scalars(
            query.order_by(desc(PlanGenerationTuningEventRecord.created_at), desc(PlanGenerationTuningEventRecord.id)).limit(max(1, limit))
        ).all()
        return [self._to_event_model(row) for row in rows]

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, datetime):
            normalized = PlanGenerationTuningRepository._normalize_datetime(value)
            return normalized.isoformat() if normalized is not None else None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @classmethod
    def _dump(cls, value: object) -> str:
        return json.dumps(value, default=cls._json_default)

    @staticmethod
    def _load_object(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_list(raw: str | None) -> list[object]:
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _apply_run(self, record: PlanGenerationTuningRunRecord, run: PlanGenerationTuningRun) -> None:
        record.status = run.status
        record.mode = run.mode
        record.objective_name = run.objective_name
        record.promotion_mode = run.promotion_mode
        record.baseline_config_version_id = run.baseline_config_version_id
        record.winning_candidate_id = run.winning_candidate_id
        record.promoted_config_version_id = run.promoted_config_version_id
        record.eligible_record_count = run.eligible_record_count
        record.eligible_tier_a_count = run.eligible_tier_a_count
        record.validation_record_count = run.validation_record_count
        record.candidate_count = run.candidate_count
        record.summary_json = self._dump(run.summary)
        record.filters_json = self._dump(run.filters)
        record.error_message = run.error_message or ""
        record.code_version = run.code_version
        record.started_at = self._normalize_datetime(run.started_at)
        record.completed_at = self._normalize_datetime(run.completed_at)

    def _to_run_model(self, record: PlanGenerationTuningRunRecord) -> PlanGenerationTuningRun:
        return PlanGenerationTuningRun(
            id=record.id,
            status=record.status,
            mode=record.mode,
            objective_name=record.objective_name,
            promotion_mode=record.promotion_mode,
            baseline_config_version_id=record.baseline_config_version_id,
            winning_candidate_id=record.winning_candidate_id,
            promoted_config_version_id=record.promoted_config_version_id,
            eligible_record_count=record.eligible_record_count,
            eligible_tier_a_count=record.eligible_tier_a_count,
            validation_record_count=record.validation_record_count,
            candidate_count=record.candidate_count,
            summary=self._load_object(record.summary_json),
            filters=self._load_object(record.filters_json),
            candidates=self.list_candidates_for_run(record.id),
            error_message=record.error_message or None,
            code_version=record.code_version,
            started_at=self._normalize_datetime(record.started_at),
            completed_at=self._normalize_datetime(record.completed_at),
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )

    def _apply_candidate(self, record: PlanGenerationTuningCandidateRecord, candidate: PlanGenerationTuningCandidate) -> None:
        record.run_id = candidate.run_id or record.run_id
        record.rank = candidate.rank
        record.status = candidate.status
        record.is_baseline = candidate.is_baseline
        record.promotion_eligible = candidate.promotion_eligible
        record.config_json = self._dump(candidate.config)
        record.changed_keys_json = self._dump(candidate.changed_keys)
        record.score_summary_json = self._dump(candidate.score_summary)
        record.metric_breakdown_json = self._dump(candidate.metric_breakdown)
        record.sample_breakdown_json = self._dump(candidate.sample_breakdown)
        record.validation_summary_json = self._dump(candidate.validation_summary)
        record.rejection_reasons_json = self._dump(candidate.rejection_reasons)

    def _to_candidate_model(self, record: PlanGenerationTuningCandidateRecord) -> PlanGenerationTuningCandidate:
        return PlanGenerationTuningCandidate(
            id=record.id,
            run_id=record.run_id,
            rank=record.rank,
            status=record.status,
            is_baseline=record.is_baseline,
            promotion_eligible=record.promotion_eligible,
            config=self._load_object(record.config_json),
            changed_keys=[str(item) for item in self._load_list(record.changed_keys_json)],
            score_summary=self._load_object(record.score_summary_json),
            metric_breakdown=self._load_object(record.metric_breakdown_json),
            sample_breakdown=self._load_object(record.sample_breakdown_json),
            validation_summary=self._load_object(record.validation_summary_json),
            rejection_reasons=[str(item) for item in self._load_list(record.rejection_reasons_json)],
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )

    def _apply_config_version(self, record: PlanGenerationTuningConfigVersionRecord, version: PlanGenerationTuningConfigVersion) -> None:
        record.version_label = version.version_label
        record.status = version.status
        record.source = version.source
        record.parent_config_version_id = version.parent_config_version_id
        record.source_run_id = version.source_run_id
        record.source_candidate_id = version.source_candidate_id
        record.config_json = self._dump(version.config)
        record.parameter_schema_version = version.parameter_schema_version

    def _to_config_version_model(self, record: PlanGenerationTuningConfigVersionRecord) -> PlanGenerationTuningConfigVersion:
        return PlanGenerationTuningConfigVersion(
            id=record.id,
            version_label=record.version_label,
            status=record.status,
            source=record.source,
            parent_config_version_id=record.parent_config_version_id,
            source_run_id=record.source_run_id,
            source_candidate_id=record.source_candidate_id,
            config=self._load_object(record.config_json),
            parameter_schema_version=record.parameter_schema_version,
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )

    def _apply_event(self, record: PlanGenerationTuningEventRecord, event: PlanGenerationTuningEvent) -> None:
        record.event_type = event.event_type
        record.run_id = event.run_id
        record.config_version_id = event.config_version_id
        record.candidate_id = event.candidate_id
        record.actor_type = event.actor_type
        record.actor_identifier = event.actor_identifier
        record.payload_json = self._dump(event.payload)

    def _to_event_model(self, record: PlanGenerationTuningEventRecord) -> PlanGenerationTuningEvent:
        return PlanGenerationTuningEvent(
            id=record.id,
            event_type=record.event_type,
            run_id=record.run_id,
            config_version_id=record.config_version_id,
            candidate_id=record.candidate_id,
            actor_type=record.actor_type,
            actor_identifier=record.actor_identifier,
            payload=self._load_object(record.payload_json),
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )
