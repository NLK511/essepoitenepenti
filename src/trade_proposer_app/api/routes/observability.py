from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository


router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/events")
async def list_observability_events(
    run_id: int | None = None,
    correlation_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = ObservabilityEventRepository(session)
    events = repository.list_events(
        run_id=run_id,
        correlation_id=correlation_id,
        severity=severity,
        limit=limit,
    )
    return {"events": events, "count": len(events)}
