from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationSignalGatingTuningRun
from trade_proposer_app.services.signal_gating_tuning import RecommendationSignalGatingTuningError, RecommendationSignalGatingTuningService

router = APIRouter(prefix="/signal-gating-tuning", tags=["signal-gating-tuning"])


@router.get("")
async def get_signal_gating_tuning_state(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return RecommendationSignalGatingTuningService(session).describe()


@router.post("/run")
async def run_signal_gating_tuning(
    ticker: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    review_priority: str | None = Query(default=None),
    decision_type: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    apply: bool = Query(default=False),
    session: Session = Depends(get_db_session),
) -> RecommendationSignalGatingTuningRun:
    try:
        return RecommendationSignalGatingTuningService(session).run(
            ticker=ticker,
            run_id=run_id,
            setup_family=setup_family,
            review_priority=review_priority,
            decision_type=decision_type,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            apply=apply,
        )
    except RecommendationSignalGatingTuningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
