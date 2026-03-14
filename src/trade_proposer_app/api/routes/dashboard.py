from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(session: Session = Depends(get_db_session)) -> dict[str, object]:
    watchlists = WatchlistRepository(session).list_all()
    jobs = JobRepository(session).list_all()
    runs = RunRepository(session)
    settings = SettingsRepository(session).get_setting_map()
    try:
        confidence_threshold = float(settings.get("confidence_threshold", "60"))
    except ValueError:
        confidence_threshold = 60.0
    latest_runs = runs.list_latest_runs_above_confidence_threshold(confidence_threshold=confidence_threshold, limit=10)
    recommendations = runs.list_latest_recommendations(limit=12)
    return {
        "watchlists": watchlists,
        "jobs": jobs,
        "latest_runs": latest_runs,
        "recommendations": recommendations,
    }
