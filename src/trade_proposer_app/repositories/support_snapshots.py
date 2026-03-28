import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import SupportSnapshot
from trade_proposer_app.persistence.models import SupportSnapshotRecord


class SupportSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        scope: str,
        subject_key: str,
        subject_label: str,
        status: str = "completed",
        score: float = 0.0,
        label: str = "NEUTRAL",
        computed_at: datetime | None = None,
        expires_at: datetime | None = None,
        coverage: dict[str, object] | None = None,
        source_breakdown: dict[str, object] | None = None,
        drivers: list[str] | None = None,
        signals: dict[str, object] | None = None,
        diagnostics: dict[str, object] | None = None,
        summary_text: str = "",
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> SupportSnapshot:
        record = SupportSnapshotRecord(
            scope=scope,
            subject_key=subject_key,
            subject_label=subject_label,
            status=status,
            score=score,
            label=label,
            computed_at=computed_at or datetime.now(timezone.utc),
            expires_at=expires_at,
            coverage_json=self._serialize(coverage or {}),
            source_breakdown_json=self._serialize(source_breakdown or {}),
            drivers_json=self._serialize(drivers or []),
            signals_json=self._serialize(signals or {}),
            diagnostics_json=self._serialize(diagnostics or {}),
            summary_text=summary_text,
            job_id=job_id,
            run_id=run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def get_snapshot(self, snapshot_id: int) -> SupportSnapshot | None:
        record = self.session.get(SupportSnapshotRecord, snapshot_id)
        if record is None:
            return None
        return self._to_model(record)

    def get_latest_snapshot(self, scope: str, subject_key: str) -> SupportSnapshot | None:
        record = self.session.scalars(
            select(SupportSnapshotRecord)
            .where(SupportSnapshotRecord.scope == scope)
            .where(SupportSnapshotRecord.subject_key == subject_key)
            .order_by(SupportSnapshotRecord.computed_at.desc())
            .limit(1)
        ).first()
        if record is None:
            return None
        return self._to_model(record)

    def get_latest_valid_snapshot(self, scope: str, subject_key: str, now: datetime | None = None) -> SupportSnapshot | None:
        reference = now or datetime.now(timezone.utc)
        snapshot = self.get_latest_snapshot(scope, subject_key)
        if snapshot is None:
            return None
        if snapshot.expires_at is not None and self._normalize(snapshot.expires_at) < self._normalize(reference):
            return None
        return snapshot

    def list_recent_snapshots(self, scope: str | None = None, limit: int = 50) -> list[SupportSnapshot]:
        query = select(SupportSnapshotRecord).order_by(SupportSnapshotRecord.computed_at.desc()).limit(limit)
        if scope:
            query = query.where(SupportSnapshotRecord.scope == scope)
        rows = self.session.scalars(query).all()
        return [self._to_model(row) for row in rows]

    @classmethod
    def _to_model(cls, record: SupportSnapshotRecord) -> SupportSnapshot:
        return SupportSnapshot(
            id=record.id,
            scope=record.scope,
            subject_key=record.subject_key,
            subject_label=record.subject_label,
            status=record.status,
            score=record.score,
            label=record.label,
            computed_at=cls._normalize(record.computed_at),
            expires_at=cls._normalize(record.expires_at) if record.expires_at else None,
            coverage_json=record.coverage_json or None,
            source_breakdown_json=record.source_breakdown_json or None,
            drivers_json=record.drivers_json or None,
            signals_json=record.signals_json or None,
            diagnostics_json=record.diagnostics_json or None,
            summary_text=record.summary_text or "",
            job_id=record.job_id,
            run_id=record.run_id,
        )

    @staticmethod
    def _serialize(value: dict[str, object] | list[object]) -> str:
        return json.dumps(value, indent=2, sort_keys=True)

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


SupportSnapshotRepository = SupportSnapshotRepository
