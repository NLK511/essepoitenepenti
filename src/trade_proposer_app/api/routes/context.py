from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot, TickerSignalSnapshot
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository

router = APIRouter(prefix="/context", tags=["context"])


@router.get("/macro")
async def list_macro_context_snapshots(
    limit: int = Query(default=20, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[MacroContextSnapshot]:
    return ContextSnapshotRepository(session).list_macro_context_snapshots(limit=limit, run_id=run_id)


@router.get("/macro/{snapshot_id}")
async def get_macro_context_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
) -> MacroContextSnapshot:
    snapshot = ContextSnapshotRepository(session).get_macro_context_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Macro context snapshot not found")
    return snapshot


@router.get("/industry")
async def list_industry_context_snapshots(
    industry_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[IndustryContextSnapshot]:
    return ContextSnapshotRepository(session).list_industry_context_snapshots(
        industry_key=industry_key,
        limit=limit,
        run_id=run_id,
    )


@router.get("/industry/{snapshot_id}")
async def get_industry_context_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
) -> IndustryContextSnapshot:
    snapshot = ContextSnapshotRepository(session).get_industry_context_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Industry context snapshot not found")
    return snapshot


@router.get("/ticker-signals")
async def list_ticker_signal_snapshots(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    run_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[TickerSignalSnapshot]:
    normalized_ticker = ticker.strip().upper() if ticker else None
    return ContextSnapshotRepository(session).list_ticker_signal_snapshots(
        ticker=normalized_ticker,
        limit=limit,
        run_id=run_id,
    )
