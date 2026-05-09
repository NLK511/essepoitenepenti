from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.data_quality_audit import DataQualityAuditService

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get("/audit")
async def get_data_quality_audit(
    watchlist_id: int | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    stale_after_days: int = Query(default=14, ge=1, le=365),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return DataQualityAuditService(session).summarize(
        watchlist_id=watchlist_id,
        ticker=ticker,
        limit=limit,
        stale_after_days=stale_after_days,
    )
