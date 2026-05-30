from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService
from trade_proposer_app.services.fundamental_analysis_refresh import FundamentalAnalysisRefreshService
from trade_proposer_app.services.fundamental_validation_slices import FundamentalValidationSliceService
from trade_proposer_app.services.monitored_tickers import MonitoredTickerService

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


def _json_snapshot(snapshot: dict[str, object] | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    payload = dict(snapshot)
    for key in ("as_of", "created_at", "updated_at"):
        value = payload.get(key)
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


@router.get("/monitored-tickers")
async def list_monitored_tickers(session: Session = Depends(get_db_session)) -> dict[str, object]:
    rows = MonitoredTickerService(session).list_monitored_tickers_with_provenance()
    return {"count": len(rows), "tickers": rows}


@router.get("/snapshots/{ticker}/latest")
async def latest_fundamental_snapshot(
    ticker: str,
    as_of: datetime | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repo = FundamentalAnalysisSnapshotRepository(session)
    snapshot = repo.get_latest_at_or_before(ticker, as_of) if as_of is not None else repo.get_latest_for_ticker(ticker)
    return {"ticker": ticker.strip().upper(), "snapshot": _json_snapshot(snapshot)}


@router.post("/snapshots/{ticker}/refresh")
async def refresh_fundamental_snapshot(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repo = FundamentalAnalysisSnapshotRepository(session)
    snapshot = FundamentalAnalysisService(repository=repo).refresh_ticker(ticker, as_of=datetime.now(timezone.utc))
    return {"ticker": ticker.strip().upper(), "snapshot": _json_snapshot(snapshot)}


@router.post("/refresh-due")
async def refresh_due_fundamental_snapshots(
    max_tickers: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return FundamentalAnalysisRefreshService(session).refresh_due_monitored_tickers(max_tickers=max_tickers)


@router.get("/validation-slices")
async def fundamental_validation_slices(
    limit: int = Query(default=5000, ge=1, le=20000),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return FundamentalValidationSliceService(session).summarize(limit=limit)
