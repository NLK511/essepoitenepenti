from fastapi import APIRouter

from trade_proposer_app.api.routes.auth import router as auth_router
from trade_proposer_app.api.routes.dashboard import router as dashboard_router
from trade_proposer_app.api.routes.docs import router as docs_router
from trade_proposer_app.api.routes.health import router as health_router
from trade_proposer_app.api.routes.history import router as history_router
from trade_proposer_app.api.routes.jobs import router as jobs_router
from trade_proposer_app.api.routes.recommendations import router as recommendations_router
from trade_proposer_app.api.routes.runs import router as runs_router
from trade_proposer_app.api.routes.settings import router as settings_router
from trade_proposer_app.api.routes.tickers import router as tickers_router
from trade_proposer_app.api.routes.watchlists import router as watchlists_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(history_router)
router.include_router(docs_router)
router.include_router(recommendations_router)
router.include_router(watchlists_router)
router.include_router(jobs_router)
router.include_router(runs_router)
router.include_router(settings_router)
router.include_router(tickers_router)
