from fastapi import APIRouter

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import AppPreflightReport
from trade_proposer_app.services.preflight import AppPreflightService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    report = AppPreflightService().run()
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
async def preflight_health() -> AppPreflightReport:
    return AppPreflightService().run()


@router.get("/health/prototype")
async def prototype_health() -> AppPreflightReport:
    return AppPreflightService().run()
