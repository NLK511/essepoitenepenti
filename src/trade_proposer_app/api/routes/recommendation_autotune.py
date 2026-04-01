from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import RecommendationAutotuneRun
from trade_proposer_app.services.recommendation_autotune import RecommendationAutotuneError, RecommendationAutotuneService

router = APIRouter(prefix="/signal-gating-tuning", tags=["signal-gating-tuning"])
legacy_router = APIRouter(prefix="/recommendation-autotune", tags=["recommendation-autotune"])


@router.get("")
@legacy_router.get("")
async def get_signal_gating_tuning_state(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return RecommendationAutotuneService(session).describe()


@router.post("/run")
@legacy_router.post("/run")
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
) -> RecommendationAutotuneRun:
    try:
        return RecommendationAutotuneService(session).run(
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
    except RecommendationAutotuneError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
