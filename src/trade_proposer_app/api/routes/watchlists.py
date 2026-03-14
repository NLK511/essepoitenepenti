from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import Watchlist
from trade_proposer_app.repositories.watchlists import WatchlistRepository

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def parse_tickers(raw: str) -> list[str]:
    return [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]


@router.get("")
async def list_watchlists(session: Session = Depends(get_db_session)) -> list[Watchlist]:
    return WatchlistRepository(session).list_all()


@router.post("")
async def create_watchlist(
    name: str = Form(...),
    tickers: str = Form(...),
    session: Session = Depends(get_db_session),
) -> Watchlist:
    try:
        return WatchlistRepository(session).create(name=name.strip(), tickers=parse_tickers(tickers))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
