from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from trade_proposer_app.api.router import router as api_router
from trade_proposer_app.config import settings
from trade_proposer_app.security.auth import SingleUserAuthMiddleware
from trade_proposer_app.web.router import FRONTEND_DIST_DIR, router as web_router


@asynccontextmanager
async def lifespan(_: FastAPI):
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
