from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import ObservabilityEventRecord


class ObservabilityEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        event_type: str,
        severity: str = "info",
        source: str = "app",
        message: str = "",
        run_id: int | None = None,
        job_id: int | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        record = ObservabilityEventRecord(
            run_id=run_id,
            job_id=job_id,
            correlation_id=(correlation_id or "").strip() or None,
            event_type=event_type.strip(),
            severity=severity.strip().lower() or "info",
            source=source.strip() or "app",
            message=message.strip(),
            payload_json=json.dumps(payload or {}, sort_keys=True),
            created_at=self._normalize_datetime(created_at) or datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dict(record)

    def list_events(
        self,
        *,
        run_id: int | None = None,
        correlation_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = select(ObservabilityEventRecord).order_by(ObservabilityEventRecord.created_at.desc(), ObservabilityEventRecord.id.desc())
        if run_id is not None:
            query = query.where(ObservabilityEventRecord.run_id == run_id)
        if correlation_id:
            query = query.where(ObservabilityEventRecord.correlation_id == correlation_id.strip())
        if severity:
            query = query.where(ObservabilityEventRecord.severity == severity.strip().lower())
        query = query.limit(max(1, min(int(limit), 500)))
        return [self._to_dict(record) for record in self.session.scalars(query).all()]

    @classmethod
    def _to_dict(cls, record: ObservabilityEventRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "run_id": record.run_id,
            "job_id": record.job_id,
            "correlation_id": record.correlation_id,
            "event_type": record.event_type,
            "severity": record.severity,
            "source": record.source,
            "message": record.message,
            "payload": cls._loads_json_object(record.payload_json),
            "created_at": cls._normalize_datetime(record.created_at).isoformat() if cls._normalize_datetime(record.created_at) else None,
        }

    @staticmethod
    def _loads_json_object(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
