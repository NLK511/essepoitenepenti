from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import Watchlist, WatchlistEvaluationPolicy
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.watchlist_policy import WatchlistPolicyService

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def parse_tickers(raw: str) -> list[str]:
    return [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]


def parse_boolean(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def parse_horizon(raw: str | None) -> StrategyHorizon:
    normalized = (raw or StrategyHorizon.ONE_WEEK.value).strip() or StrategyHorizon.ONE_WEEK.value
    try:
        return StrategyHorizon(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="default_horizon must be one of: 1d, 1w, 1m") from exc


@router.get("")
async def list_watchlists(session: Session = Depends(get_db_session)) -> list[Watchlist]:
    return WatchlistRepository(session).list_all()


@router.get("/{watchlist_id}/policy")
async def get_watchlist_policy(
    watchlist_id: int,
    session: Session = Depends(get_db_session),
) -> WatchlistEvaluationPolicy:
    repository = WatchlistRepository(session)
    try:
        watchlist = repository.get(watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WatchlistPolicyService().describe_watchlist(watchlist)


@router.post("")
async def create_watchlist(
    name: str = Form(...),
    tickers: str = Form(...),
    description: str = Form(default=""),
    region: str = Form(default=""),
    exchange: str = Form(default=""),
    timezone: str = Form(default=""),
    default_horizon: str = Form(default=StrategyHorizon.ONE_WEEK.value),
    allow_shorts: str = Form(default="true"),
    optimize_evaluation_timing: str = Form(default="false"),
    session: Session = Depends(get_db_session),
) -> Watchlist:
    try:
        return WatchlistRepository(session).create(
            name=name.strip(),
            tickers=parse_tickers(tickers),
            description=description,
            region=region,
            exchange=exchange,
            timezone=timezone,
            default_horizon=parse_horizon(default_horizon),
            allow_shorts=parse_boolean(allow_shorts, default=True),
            optimize_evaluation_timing=parse_boolean(optimize_evaluation_timing, default=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
