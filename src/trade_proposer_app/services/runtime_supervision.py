from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import RuntimeProcess
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.runtime_processes import RuntimeProcessRepository

_RUNTIME_EVENT_SOURCE = "runtime_supervision"


class RuntimeSupervisionService:
    def __init__(self, session: Session) -> None:
        self.processes = RuntimeProcessRepository(session)
        self.events = ObservabilityEventRepository(session)

    def register_process_start(
        self,
        *,
        role: str,
        instance_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RuntimeProcess:
        timestamp = self._now(now)
        process = RuntimeProcess(
            instance_id=instance_id or build_runtime_instance_id(role),
            role=role,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            status="healthy",
            started_at=timestamp,
            last_heartbeat_at=timestamp,
            version=os.getenv("APP_VERSION") or None,
            metadata=metadata or {},
        )
        stored = self.processes.upsert_process(process)
        self._record_event(
            "process_started",
            process=stored,
            message=f"{role} process started",
            payload={"metadata": stored.metadata},
        )
        for previous in self.processes.previous_unclosed_processes(
            role=role,
            exclude_instance_id=stored.instance_id,
            stale_after_seconds=settings.runtime_process_stale_after_seconds,
        ):
            self._record_event(
                "unclean_restart_inferred",
                process=stored,
                severity="warning",
                message=(
                    f"Previous {role} process appears to have stopped without graceful shutdown"
                ),
                payload={
                    "previous_instance_id": previous.instance_id,
                    "previous_pid": previous.pid,
                    "previous_hostname": previous.hostname,
                    "previous_last_heartbeat_at": previous.last_heartbeat_at.isoformat(),
                },
            )
        return stored

    def heartbeat(
        self,
        *,
        instance_id: str,
        status: str = "healthy",
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RuntimeProcess | None:
        return self.processes.record_heartbeat(
            instance_id=instance_id,
            heartbeat_at=self._now(now),
            status=status,
            metadata=metadata,
        )

    def graceful_shutdown(
        self, *, instance_id: str, now: datetime | None = None
    ) -> RuntimeProcess | None:
        process = self.processes.record_graceful_shutdown(
            instance_id=instance_id, shutdown_at=self._now(now)
        )
        if process is not None:
            self._record_event(
                "graceful_shutdown",
                process=process,
                message=f"{process.role} process stopped gracefully",
            )
        return process

    def detect_stale_processes(self, *, now: datetime | None = None) -> list[RuntimeProcess]:
        stale = self.processes.list_stale_processes(
            stale_after_seconds=settings.runtime_process_stale_after_seconds
        )
        for process in stale:
            age_seconds = max(
                0.0,
                (self._now(now) - process.last_heartbeat_at).total_seconds(),
            )
            self._record_event(
                "stale_heartbeat_detected",
                process=process,
                severity="warning",
                message=f"{process.role} process heartbeat is stale",
                payload={"heartbeat_age_seconds": age_seconds},
            )
        return stale

    def runtime_summary(self) -> dict[str, object]:
        processes = self.processes.list_processes(limit=200)
        active = self.processes.list_active_processes(
            stale_after_seconds=settings.runtime_process_stale_after_seconds
        )
        stale = self.processes.list_stale_processes(
            stale_after_seconds=settings.runtime_process_stale_after_seconds
        )
        runtime_events = self.events.list_events(source=_RUNTIME_EVENT_SOURCE, limit=50)
        return {
            "heartbeat_interval_seconds": settings.runtime_process_heartbeat_interval_seconds,
            "stale_after_seconds": settings.runtime_process_stale_after_seconds,
            "processes": [self._process_payload(item) for item in processes],
            "active_processes": [self._process_payload(item) for item in active],
            "stale_processes": [self._process_payload(item) for item in stale],
            "counts": {
                "total": len(processes),
                "active": len(active),
                "stale": len(stale),
                "api": sum(1 for item in active if item.role == "api"),
                "worker": sum(1 for item in active if item.role == "worker"),
                "scheduler": sum(1 for item in active if item.role == "scheduler"),
                "unclean_restart_inferred": sum(
                    1
                    for item in runtime_events
                    if item.get("event_type") == "unclean_restart_inferred"
                ),
            },
        }

    def runtime_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.events.list_events(source=_RUNTIME_EVENT_SOURCE, limit=limit)

    def _record_event(
        self,
        event_type: str,
        *,
        process: RuntimeProcess,
        severity: str = "info",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        base_payload: dict[str, Any] = {
            "role": process.role,
            "instance_id": process.instance_id,
            "hostname": process.hostname,
            "pid": process.pid,
        }
        if payload:
            base_payload.update(payload)
        self.events.record(
            event_type=event_type,
            severity=severity,
            source=_RUNTIME_EVENT_SOURCE,
            message=message,
            payload=base_payload,
        )

    @staticmethod
    def _process_payload(process: RuntimeProcess) -> dict[str, Any]:
        return {
            "instance_id": process.instance_id,
            "role": process.role,
            "hostname": process.hostname,
            "pid": process.pid,
            "status": process.status,
            "started_at": process.started_at.isoformat(),
            "last_heartbeat_at": process.last_heartbeat_at.isoformat(),
            "graceful_shutdown_at": process.graceful_shutdown_at.isoformat()
            if process.graceful_shutdown_at
            else None,
            "version": process.version,
            "metadata": process.metadata,
        }

    @staticmethod
    def _now(value: datetime | None = None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)


def build_runtime_instance_id(role: str) -> str:
    env_key = f"{role.upper()}_INSTANCE_ID"
    configured = os.getenv(env_key) or os.getenv("RUNTIME_INSTANCE_ID")
    if configured:
        return configured.strip()
    return f"{role}-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
