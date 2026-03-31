from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice, Run
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.historical_replay import HistoricalReplayService

router = APIRouter(prefix="/historical-replay", tags=["historical-replay"])


def _create_service(session: Session) -> HistoricalReplayService:
    return HistoricalReplayService(
        historical_replays=HistoricalReplayRepository(session),
        jobs=JobRepository(session),
        runs=RunRepository(session),
        historical_market_data=HistoricalMarketDataService(HistoricalMarketDataRepository(session)),
    )


def _parse_date(value: str, field_name: str, *, end_of_day: bool = False) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an ISO date or datetime") from exc
    if parsed.tzinfo is None and len(value.strip()) <= 10:
        parsed = datetime.combine(parsed.date(), time(23, 59, 59) if end_of_day else time.min, tzinfo=timezone.utc)
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


@router.get("/universe-presets")
async def list_universe_presets(session: Session = Depends(get_db_session)) -> list[dict[str, object]]:
    return _create_service(session).list_universe_presets()


@router.get("/batches")
async def list_batches(session: Session = Depends(get_db_session)) -> list[HistoricalReplayBatch]:
    return HistoricalReplayRepository(session).list_batches()


@router.post("/batches")
async def create_batch(
    name: str = Form(...),
    mode: str = Form(default="research"),
    as_of_start: str = Form(...),
    as_of_end: str = Form(...),
    cadence: str = Form(default="daily"),
    universe_preset: str | None = Form(default=None),
    tickers_csv: str | None = Form(default=None),
    entry_timing: str = Form(default="next_open"),
    price_provider: str = Form(default="yahoo"),
    session: Session = Depends(get_db_session),
) -> HistoricalReplayBatch:
    try:
        explicit_tickers = [item.strip() for item in (tickers_csv or "").split(",") if item.strip()]
        return _create_service(session).create_batch(
            name=name.strip(),
            mode=mode.strip().lower(),
            as_of_start=_parse_date(as_of_start, "as_of_start"),
            as_of_end=_parse_date(as_of_end, "as_of_end", end_of_day=True),
            cadence=cadence.strip().lower(),
            universe_preset=(universe_preset.strip() if universe_preset and universe_preset.strip() else None),
            tickers=explicit_tickers or None,
            entry_timing=entry_timing.strip().lower(),
            price_provider=price_provider.strip().lower(),
            config={"created_via": "api"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    repository = HistoricalReplayRepository(session)
    try:
        batch = repository.get_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _create_service(session).get_batch_detail(batch_id)


@router.post("/batches/{batch_id}/hydrate-market-data")
async def hydrate_batch_market_data(batch_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    try:
        payload = _create_service(session).hydrate_batch_market_data(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"batch_id": batch_id, **payload}


@router.post("/batches/{batch_id}/execute")
async def execute_batch(batch_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    try:
        queued_runs = _create_service(session).enqueue_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "batch_id": batch_id,
        "queued_run_count": len(queued_runs),
        "run_ids": [run.id for run in queued_runs],
    }


@router.get("/slices/{slice_id}")
async def get_slice(slice_id: int, session: Session = Depends(get_db_session)) -> HistoricalReplaySlice:
    try:
        return HistoricalReplayRepository(session).get_slice(slice_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
