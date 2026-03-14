from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["web"])

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
SPA_ROUTES = {
    "",
    "watchlists",
    "jobs",
    "history",
    "debugger",
    "settings",
    "docs",
}


def build_frontend_missing_response() -> HTMLResponse:
    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Trade Proposer App frontend</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 760px; margin: 48px auto; padding: 0 16px; line-height: 1.6; }
      code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
    </style>
  </head>
  <body>
    <h1>Trade Proposer App frontend</h1>
    <p>The React/Vite frontend is served by the dev server during local development, or by built assets in <code>frontend/dist</code>.</p>
    <p>Local development:</p>
    <pre>./scripts/start-dev.sh</pre>
    <p>Production/static serving:</p>
    <pre>cd frontend && npm install && npm run build</pre>
    <p>The JSON API remains available under <code>/api</code>.</p>
  </body>
</html>
""",
        status_code=200,
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_spa(run_id: int) -> HTMLResponse:
    if not FRONTEND_INDEX_FILE.exists():
        return build_frontend_missing_response()
    return FileResponse(FRONTEND_INDEX_FILE)


@router.get("/tickers/{ticker}", response_class=HTMLResponse)
async def ticker_detail_spa(ticker: str) -> HTMLResponse:
    if not FRONTEND_INDEX_FILE.exists():
        return build_frontend_missing_response()
    return FileResponse(FRONTEND_INDEX_FILE)


@router.get("/recommendations/{recommendation_id}", response_class=HTMLResponse)
async def recommendation_detail_spa(recommendation_id: int) -> HTMLResponse:
    if not FRONTEND_INDEX_FILE.exists():
        return build_frontend_missing_response()
    return FileResponse(FRONTEND_INDEX_FILE)


@router.get("/{path:path}", response_class=HTMLResponse)
async def spa_entry(path: str) -> HTMLResponse:
    normalized_path = path.strip("/")
    if normalized_path not in SPA_ROUTES:
        return HTMLResponse("Not Found", status_code=404)
    if not FRONTEND_INDEX_FILE.exists():
        return build_frontend_missing_response()
    return FileResponse(FRONTEND_INDEX_FILE)
