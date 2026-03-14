from fastapi import APIRouter

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import PrototypePreflightReport
from trade_proposer_app.services.preflight import PrototypePreflightService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    prototype = PrototypePreflightService().run()
    status = "ok" if prototype.status == "ok" else "degraded"
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "prototype": {
            "status": prototype.status,
            "checked_at": prototype.checked_at.isoformat(),
        },
    }


@router.get("/health/prototype")
async def prototype_health() -> PrototypePreflightReport:
    return PrototypePreflightService().run()
