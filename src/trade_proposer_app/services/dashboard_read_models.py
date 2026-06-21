from __future__ import annotations

from typing import Any


def compact_run_payload(run: Any) -> dict[str, object]:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "job_type": run.job_type,
        "status": run.status,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": run.duration_seconds,
    }
