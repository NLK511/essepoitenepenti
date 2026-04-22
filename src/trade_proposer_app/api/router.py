from fastapi import APIRouter

from trade_proposer_app.api.routes.auth import router as auth_router
from trade_proposer_app.api.routes.context import router as context_router
from trade_proposer_app.api.routes.dashboard import router as dashboard_router
from trade_proposer_app.api.routes.docs import router as docs_router
from trade_proposer_app.api.routes.health import router as health_router
from trade_proposer_app.api.routes.historical_replay import router as historical_replay_router
from trade_proposer_app.api.routes.jobs import router as jobs_router
from trade_proposer_app.api.routes.signal_gating_tuning import router as signal_gating_tuning_router
from trade_proposer_app.api.routes.plan_generation_tuning import router as plan_generation_tuning_router
from trade_proposer_app.api.routes.recommendation_decision_samples import router as recommendation_decision_samples_router
from trade_proposer_app.api.routes.research import router as research_router
from trade_proposer_app.api.routes.recommendation_outcomes import router as recommendation_outcomes_router
from trade_proposer_app.api.routes.recommendation_plans import router as recommendation_plans_router
from trade_proposer_app.api.routes.recommendation_quality import router as recommendation_quality_router
from trade_proposer_app.api.routes.broker_orders import router as broker_orders_router
from trade_proposer_app.api.routes.runs import router as runs_router
from trade_proposer_app.api.routes.settings import router as settings_router
from trade_proposer_app.api.routes.tickers import router as tickers_router
from trade_proposer_app.api.routes.watchlists import router as watchlists_router
from trade_proposer_app.api.routes.workers import router as workers_router

router = APIRouter(prefix="/api")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(docs_router)
router.include_router(context_router)
router.include_router(historical_replay_router)
router.include_router(signal_gating_tuning_router)
router.include_router(plan_generation_tuning_router)
router.include_router(recommendation_decision_samples_router)
router.include_router(research_router)
router.include_router(recommendation_outcomes_router)
router.include_router(recommendation_plans_router)
router.include_router(recommendation_quality_router)
router.include_router(broker_orders_router)
router.include_router(watchlists_router)
router.include_router(jobs_router)
router.include_router(runs_router)
router.include_router(settings_router)
router.include_router(tickers_router)
router.include_router(workers_router)
