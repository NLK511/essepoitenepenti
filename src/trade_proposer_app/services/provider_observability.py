from __future__ import annotations

from datetime import datetime
from typing import Any

from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository


class ProviderObservabilityService:
    """Emit normalized provider lifecycle events."""

    EVENT_TYPES = {
        "started": "provider.request_started",
        "succeeded": "provider.request_succeeded",
        "failed": "provider.request_failed",
        "skipped": "provider.request_skipped",
    }

    def __init__(self, repository: ObservabilityEventRepository) -> None:
        self.repository = repository

    def record(
        self,
        status: str,
        *,
        provider: str,
        source_type: str,
        ticker: str | None = None,
        topic: str | None = None,
        as_of: datetime | str | None = None,
        window: str | None = None,
        mode: str = "live",
        attempt: int | None = None,
        duration_ms: float | None = None,
        reason: str = "",
        run_id: int | None = None,
        job_id: int | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_status = status.strip().lower()
        event_type = self.EVENT_TYPES.get(normalized_status)
        if event_type is None:
            raise ValueError(f"unsupported provider event status: {status}")
        event_payload: dict[str, Any] = {
            "provider": provider,
            "source_type": source_type,
            "ticker": ticker.strip().upper() if ticker else None,
            "topic": topic,
            "as_of": as_of.isoformat() if isinstance(as_of, datetime) else as_of,
            "window": window,
            "mode": mode,
            "attempt": attempt,
            "duration_ms": duration_ms,
            "reason": reason,
        }
        if payload:
            event_payload.update(payload)
        severity = "warning" if normalized_status == "failed" else "info"
        message = reason or f"Provider request {normalized_status}"
        return self.repository.record(
            event_type=event_type,
            severity=severity,
            source="provider",
            message=message,
            run_id=run_id,
            job_id=job_id,
            correlation_id=correlation_id,
            payload=event_payload,
        )
