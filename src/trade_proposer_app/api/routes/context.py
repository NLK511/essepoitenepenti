from fastapi import APIRouter, Depends, Query
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
