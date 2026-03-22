import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import SentimentSnapshot
from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository

router = APIRouter(prefix="/sentiment-snapshots", tags=["sentiment-snapshots"])


@router.get("")
async def list_sentiment_snapshots(
    scope: str | None = None,
    limit: int = 20,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = SentimentSnapshotRepository(session)
    normalized_scope = (scope or "").strip().lower() or None
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope=normalized_scope, limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": normalized_scope,
        "limit": normalized_limit,
    }


@router.get("/macro")
async def list_macro_snapshots(limit: int = 20, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SentimentSnapshotRepository(session)
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope="macro", limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": "macro",
        "limit": normalized_limit,
    }


@router.get("/industry")
async def list_industry_snapshots(limit: int = 20, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = SentimentSnapshotRepository(session)
    normalized_limit = max(1, min(limit, 100))
    snapshots = repository.list_recent_snapshots(scope="industry", limit=normalized_limit)
    return {
        "snapshots": [_serialize_snapshot(snapshot) for snapshot in snapshots],
        "scope": "industry",
        "limit": normalized_limit,
    }


@router.get("/{snapshot_id}")
async def get_sentiment_snapshot(snapshot_id: int, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    repository = SentimentSnapshotRepository(session)
    snapshot = repository.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Sentiment snapshot {snapshot_id} not found")
    return _serialize_snapshot(snapshot)


def _serialize_snapshot(snapshot: SentimentSnapshot) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires_at = snapshot.expires_at
    is_expired = expires_at is not None and expires_at < now
    return {
        "id": snapshot.id,
        "scope": snapshot.scope,
        "subject_key": snapshot.subject_key,
        "subject_label": snapshot.subject_label,
        "status": snapshot.status,
        "score": snapshot.score,
        "label": snapshot.label,
        "computed_at": snapshot.computed_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "is_expired": is_expired,
        "coverage": _parse_json(snapshot.coverage_json, {}),
        "source_breakdown": _parse_json(snapshot.source_breakdown_json, {}),
        "drivers": _parse_json(snapshot.drivers_json, []),
        "signals": _parse_json(snapshot.signals_json, {}),
        "diagnostics": _parse_json(snapshot.diagnostics_json, {}),
        "job_id": snapshot.job_id,
        "run_id": snapshot.run_id,
    }


def _parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
