import threading
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
    ensure_default_performance_assessment_job,
    ensure_default_recommendation_calibration_refresh_job,
    ensure_default_recommendation_evaluation_jobs,
)
from trade_proposer_app.services.runtime_supervision import (
    RuntimeSupervisionService,
    build_runtime_instance_id,
)
from trade_proposer_app.web.router import FRONTEND_DIST_DIR
from trade_proposer_app.web.router import router as web_router


def _api_runtime_heartbeat_loop(instance_id: str, stop_event: threading.Event) -> None:
    interval_seconds = max(5, int(settings.runtime_process_heartbeat_interval_seconds))
    while not stop_event.wait(interval_seconds):
        session = SessionLocal()
        try:
            RuntimeSupervisionService(session).heartbeat(instance_id=instance_id, status="healthy")
        finally:
            session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    api_instance_id = build_runtime_instance_id("api")
    stop_event = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    session = SessionLocal()
    try:
        RuntimeSupervisionService(session).register_process_start(
            role="api", instance_id=api_instance_id
        )
        ensure_default_broker_accounts(session)
        ensure_default_performance_assessment_job(session)
        ensure_default_recommendation_evaluation_jobs(session)
        ensure_default_broker_steering_job(session)
        ensure_default_fundamental_analysis_job(session)
        ensure_default_gating_severity_check_job(session)
        ensure_default_recommendation_calibration_refresh_job(session)
        heartbeat_thread = threading.Thread(
            target=_api_runtime_heartbeat_loop,
            args=(api_instance_id, stop_event),
            daemon=True,
        )
        heartbeat_thread.start()
    finally:
        session.close()
    try:
        yield
    finally:
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=5)
        session = SessionLocal()
        try:
            RuntimeSupervisionService(session).graceful_shutdown(instance_id=api_instance_id)
        finally:
            session.close()


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
