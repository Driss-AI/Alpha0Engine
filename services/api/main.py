"""
Alpha0Engine — FastAPI Gateway v0.6.0
Serves API endpoints + web dashboard at root.
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
load_dotenv()

from shared.config import ALLOWED_ORIGINS, AUTO_CREATE_TABLES, LOG_LEVEL, API_SECRET_KEY, VIEWER_API_KEY, IS_DEV
from shared.logging import setup_logging, get_logger

setup_logging("alpha0-api", level=LOG_LEVEL)
logger = get_logger("alpha0-api")

from shared.clients.postgres import create_db_and_tables
from middleware.auth import require_api_key
from middleware.rate_limit import setup_rate_limiting
from routers import (
    health,
    entities,
    signals,
    themes,
    ipo,
    dashboard,
    fundamentals,
    risk,
    screener_1000x,
    prices,
    pipeline_health,
    watchlist,
    deep_dive,
    deltas,
    catalysts,
    brain,
    metrics,
    data_freshness,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if AUTO_CREATE_TABLES:
        try:
            await create_db_and_tables()
            logger.info("Dev mode: create_all() completed")
        except Exception as e:
            logger.error(f"DB init failed: {e}")
    else:
        logger.info("Production mode: skipping create_all() — use Alembic migrations")
    yield


app = FastAPI(
    title="Alpha0Engine API",
    description="Asymmetric return screening engine — pre-IPO to early public market intelligence.",
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_rate_limiting(app)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/health/", "/favicon.ico", "/api/v1/metrics"):
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            f"{request.method} {request.url.path} → {response.status_code}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


app.add_middleware(RequestLoggingMiddleware)

DASHBOARD_HTML = Path(__file__).parent / "static" / "dashboard.html"
SCREENER_HTML  = Path(__file__).parent / "static" / "screener-1000x.html"


# ── Public routes (no auth: dashboard HTML + health) ──

def _inject_api_key(html: str) -> str:
    """Inject the read-only viewer key into dashboard HTML so JS can authenticate GETs.

    SECURITY: Never inject `API_SECRET_KEY` (admin) — it would let any visitor write.
    If `VIEWER_API_KEY` is not set:
      - dev mode: fall back to the admin key (no harm — there's no admin key in dev anyway)
      - prod: inject empty string; dashboard reads will 401 until VIEWER_API_KEY is set
        (intentional — surfaces the misconfiguration rather than re-introducing the leak).
    """
    if VIEWER_API_KEY:
        key_to_inject = VIEWER_API_KEY
    elif IS_DEV and not API_SECRET_KEY:
        # Dev with no auth at all — bypass mode. Use a marker string for clarity.
        key_to_inject = "dev-bypass"
    else:
        logger.warning(
            "VIEWER_API_KEY not set in non-dev environment — dashboard reads will fail. "
            "Set VIEWER_API_KEY env var (different from API_SECRET_KEY) to fix."
        )
        key_to_inject = ""
    return html.replace(
        "if(typeof API_KEY==='undefined')var API_KEY='';",
        f"var API_KEY='{key_to_inject}';",
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    if DASHBOARD_HTML.exists():
        return HTMLResponse(_inject_api_key(DASHBOARD_HTML.read_text()))
    return HTMLResponse("<h1>Alpha0Engine</h1><p>Dashboard loading...</p>")


@app.get("/screener", response_class=HTMLResponse, include_in_schema=False)
async def screener():
    if SCREENER_HTML.exists():
        return HTMLResponse(_inject_api_key(SCREENER_HTML.read_text()))
    return HTMLResponse("<h1>1000x Screener</h1><p>UI not found.</p>")


# ── Health + Metrics (no auth) ──
app.include_router(health.router)
app.include_router(metrics.router, prefix="/api/v1")

# ── Read-only API routes (viewer key) ──
_viewer = [Depends(require_api_key)]

app.include_router(dashboard.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(entities.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(signals.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(themes.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(ipo.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(fundamentals.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(risk.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(deep_dive.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(deltas.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(screener_1000x.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(prices.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(pipeline_health.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(watchlist.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(catalysts.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(data_freshness.router, prefix="/api/v1", dependencies=_viewer)
app.include_router(brain.router, prefix="/api/v1", dependencies=_viewer)
