from fastapi import APIRouter

from trade_proposer_app.api.routes.auth import router as auth_router
from trade_proposer_app.api.routes.context import router as context_router
from trade_proposer_app.api.routes.dashboard import router as dashboard_router
from trade_proposer_app.api.routes.docs import router as docs_router
from trade_proposer_app.api.routes.health import router as health_router
from trade_proposer_app.api.routes.history import router as history_router
from trade_proposer_app.api.routes.jobs import router as jobs_router
from trade_proposer_app.api.routes.recommendation_outcomes import router as recommendation_outcomes_router
from trade_proposer_app.api.routes.recommendation_plans import router as recommendation_plans_router
from trade_proposer_app.api.routes.runs import router as runs_router
from trade_proposer_app.api.routes.sentiment_snapshots import router as sentiment_snapshots_router
from trade_proposer_app.api.routes.settings import router as settings_router
from trade_proposer_app.api.routes.tickers import router as tickers_router
from trade_proposer_app.api.routes.watchlists import router as watchlists_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(history_router)
router.include_router(docs_router)
router.include_router(context_router)
router.include_router(recommendation_outcomes_router)
router.include_router(recommendation_plans_router)
router.include_router(watchlists_router)
router.include_router(jobs_router)
router.include_router(runs_router)
router.include_router(sentiment_snapshots_router)
router.include_router(settings_router)
router.include_router(tickers_router)
