from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.runs import RunRepository

router = APIRouter(prefix="/workers", tags=["workers"])
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
WORKER_LOG_DIRECTORIES = (
    WORKSPACE_ROOT / ".dev-run" / "workers",
    WORKSPACE_ROOT / ".prod-run" / "workers",
)


def _tail_lines(path: Path, limit: int) -> tuple[list[str], bool, int]:
    if limit <= 0:
        return [], False, 0
    lines = deque(maxlen=limit)
    total = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            total += 1
            lines.append(line.rstrip("\n"))
    return list(lines), total > limit, total


def _resolve_worker_log_path(worker_id: str) -> Path | None:
    for directory in WORKER_LOG_DIRECTORIES:
        path = directory / f"{worker_id}.log"
        if path.exists():
            return path
    return None


@router.get("/active")
async def active_workers(session: Session = Depends(get_db_session)) -> dict[str, object]:
    stale_seconds = settings.worker_heartbeat_interval_seconds * 2
    workers = RunRepository(session).list_active_workers(stale_seconds=stale_seconds)
    return {
        "status": "ok" if workers else "warning",
        "count": len(workers),
        "stale_seconds": stale_seconds,
        "workers": [worker.model_dump(mode="json") for worker in workers],
    }


@router.get("/{worker_id}/logs")
async def worker_logs(worker_id: str, tail: int = Query(default=200, ge=1, le=2000)) -> dict[str, object]:
    log_path = _resolve_worker_log_path(worker_id)
    if log_path is None:
        raise HTTPException(status_code=404, detail=f"No log file found for worker {worker_id}")

    lines, truncated, line_count = _tail_lines(log_path, tail)
    stat = log_path.stat()
    return {
        "worker_id": worker_id,
        "log_path": str(log_path),
        "tail": tail,
        "line_count": line_count,
        "truncated": truncated,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "lines": lines,
    }
