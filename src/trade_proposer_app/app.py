from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from trade_proposer_app.api.router import router as api_router
from trade_proposer_app.config import settings
from trade_proposer_app.db import SessionLocal
from trade_proposer_app.security.auth import SingleUserAuthMiddleware
from trade_proposer_app.services.default_jobs import (
    ensure_default_broker_accounts,
    ensure_default_broker_steering_job,
    ensure_default_fundamental_analysis_job,
    ensure_default_gating_severity_check_job,
    ensure_default_recommendation_calibration_refresh_job,
    ensure_default_recommendation_evaluation_jobs,
)
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.web.router import FRONTEND_DIST_DIR
from trade_proposer_app.web.router import router as web_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    session = SessionLocal()
    try:
        ensure_default_broker_accounts(session)
        PerformanceAssessmentService(session).ensure_daily_job()
        ensure_default_recommendation_evaluation_jobs(session)
        ensure_default_broker_steering_job(session)
        ensure_default_fundamental_analysis_job(session)
        ensure_default_gating_severity_check_job(session)
        ensure_default_recommendation_calibration_refresh_job(session)
    finally:
        session.close()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/api/openapi",
    redoc_url=None,
)
frontend_assets_dir = FRONTEND_DIST_DIR / "assets"

app.add_middleware(
    SingleUserAuthMiddleware,
    settings=settings,
)

if frontend_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_assets_dir), name="assets")

app.include_router(api_router)
app.include_router(web_router)
