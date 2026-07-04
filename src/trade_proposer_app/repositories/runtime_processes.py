from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RuntimeProcess
from trade_proposer_app.persistence.models import RuntimeProcessRecord
from trade_proposer_app.utils.json_payloads import loads_json_object


class RuntimeProcessRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_process(self, process: RuntimeProcess) -> RuntimeProcess:
        record = self.session.get(RuntimeProcessRecord, process.instance_id)
        if record is None:
            record = RuntimeProcessRecord(instance_id=process.instance_id)
            self.session.add(record)
        self._apply(record, process)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def record_heartbeat(
        self,
        *,
        instance_id: str,
        heartbeat_at: datetime | None = None,
        status: str = "healthy",
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeProcess | None:
        record = self.session.get(RuntimeProcessRecord, instance_id)
        if record is None:
            return None
        record.last_heartbeat_at = self._normalize_datetime(heartbeat_at) or datetime.now(
            timezone.utc
        ).replace(tzinfo=None)
        record.status = status.strip() or "healthy"
        if metadata is not None:
            record.metadata_json = json.dumps(self._safe_metadata(metadata), sort_keys=True)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def record_graceful_shutdown(
        self, *, instance_id: str, shutdown_at: datetime | None = None
    ) -> RuntimeProcess | None:
        record = self.session.get(RuntimeProcessRecord, instance_id)
        if record is None:
            return None
        timestamp = self._normalize_datetime(shutdown_at) or datetime.now(timezone.utc).replace(
            tzinfo=None
        )
        record.graceful_shutdown_at = timestamp
        record.last_heartbeat_at = timestamp
        record.status = "stopped"
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_processes(self, *, role: str | None = None, limit: int = 100) -> list[RuntimeProcess]:
        query = select(RuntimeProcessRecord).order_by(
            RuntimeProcessRecord.last_heartbeat_at.desc(), RuntimeProcessRecord.instance_id.asc()
        )
        if role:
            query = query.where(RuntimeProcessRecord.role == role.strip())
        query = query.limit(max(1, min(int(limit), 500)))
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    def list_active_processes(
        self, *, stale_after_seconds: int = 90, role: str | None = None
    ) -> list[RuntimeProcess]:
        stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=max(1, int(stale_after_seconds))
        )
        query = select(RuntimeProcessRecord).where(
            RuntimeProcessRecord.last_heartbeat_at >= stale_before,
            RuntimeProcessRecord.status != "stopped",
        )
        if role:
            query = query.where(RuntimeProcessRecord.role == role.strip())
        query = query.order_by(RuntimeProcessRecord.last_heartbeat_at.desc())
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    def list_stale_processes(
        self, *, stale_after_seconds: int = 90, role: str | None = None
    ) -> list[RuntimeProcess]:
        stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=max(1, int(stale_after_seconds))
        )
        query = select(RuntimeProcessRecord).where(
            RuntimeProcessRecord.last_heartbeat_at < stale_before,
            RuntimeProcessRecord.status != "stopped",
            RuntimeProcessRecord.graceful_shutdown_at.is_(None),
        )
        if role:
            query = query.where(RuntimeProcessRecord.role == role.strip())
        query = query.order_by(RuntimeProcessRecord.last_heartbeat_at.desc())
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    def previous_unclosed_processes(
        self, *, role: str, exclude_instance_id: str, stale_after_seconds: int
    ) -> list[RuntimeProcess]:
        stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=max(1, int(stale_after_seconds))
        )
        query = (
            select(RuntimeProcessRecord)
            .where(
                RuntimeProcessRecord.role == role.strip(),
                RuntimeProcessRecord.instance_id != exclude_instance_id,
                RuntimeProcessRecord.graceful_shutdown_at.is_(None),
                RuntimeProcessRecord.last_heartbeat_at < stale_before,
                RuntimeProcessRecord.status != "stopped",
            )
            .order_by(RuntimeProcessRecord.last_heartbeat_at.desc())
        )
        return [self._to_model(record) for record in self.session.scalars(query).all()]

    @classmethod
    def _apply(cls, record: RuntimeProcessRecord, process: RuntimeProcess) -> None:
        record.role = process.role.strip()
        record.hostname = process.hostname.strip()
        record.pid = int(process.pid)
        record.status = process.status.strip() or "healthy"
        record.started_at = cls._normalize_datetime(process.started_at) or datetime.now(
            timezone.utc
        ).replace(tzinfo=None)
        record.last_heartbeat_at = (
            cls._normalize_datetime(process.last_heartbeat_at) or record.started_at
        )
        record.graceful_shutdown_at = cls._normalize_datetime(process.graceful_shutdown_at)
        record.version = process.version
        record.metadata_json = json.dumps(cls._safe_metadata(process.metadata), sort_keys=True)

    @classmethod
    def _to_model(cls, record: RuntimeProcessRecord) -> RuntimeProcess:
        return RuntimeProcess(
            instance_id=record.instance_id,
            role=record.role,
            hostname=record.hostname,
            pid=record.pid,
            status=record.status,
            started_at=cls._aware(record.started_at),
            last_heartbeat_at=cls._aware(record.last_heartbeat_at),
            graceful_shutdown_at=cls._aware(record.graceful_shutdown_at),
            version=record.version,
            metadata=loads_json_object(record.metadata_json),
            created_at=cls._aware(record.created_at),
            updated_at=cls._aware(record.updated_at),
        )

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        unsafe = {
            "password",
            "token",
            "secret",
            "api_key",
            "api_secret",
            "x_user_key",
            "x-user-key",
        }
        safe: dict[str, Any] = {}
        for key, value in metadata.items():
            lowered = str(key).strip().lower()
            if any(marker in lowered for marker in unsafe):
                safe[str(key)] = "[redacted]"
            else:
                safe[str(key)] = value
        return safe
