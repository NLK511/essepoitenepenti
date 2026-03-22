from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import AppPreflightReport
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.preflight import AppPreflightService

router = APIRouter(tags=["health"])


def _create_preflight_service(session: Session) -> AppPreflightService:
    social_settings = SettingsRepository(session).get_social_settings()
    try:
        return AppPreflightService(social_settings)
    except TypeError:
        return AppPreflightService()


@router.get("/health")
async def health(session: Session = Depends(get_db_session)) -> dict[str, object]:
    report = _create_preflight_service(session).run()
    status = "ok" if report.status == "ok" else "degraded"
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "preflight": {
            "status": report.status,
            "engine": report.engine,
            "checked_at": report.checked_at.isoformat(),
        },
    }


@router.get("/health/preflight")
async def preflight_health(session: Session = Depends(get_db_session)) -> AppPreflightReport:
    return _create_preflight_service(session).run()


@router.get("/health/prototype")
async def prototype_health(session: Session = Depends(get_db_session)) -> AppPreflightReport:
    return _create_preflight_service(session).run()
