"""
Alpha0Engine — FastAPI Gateway v0.6.0
Serves API endpoints + web dashboard at root.
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
load_dotenv()

from shared.config import ALLOWED_ORIGINS, AUTO_CREATE_TABLES, IS_PROD, LOG_LEVEL, API_SECRET_KEY

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("alpha0-api")

from shared.clients.postgres import create_db_and_tables
from middleware.auth import require_api_key, require_admin_key
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

DASHBOARD_HTML = Path(__file__).parent / "static" / "dashboard.html"
SCREENER_HTML  = Path(__file__).parent / "static" / "screener-1000x.html"


# ── Public routes (no auth: dashboard HTML + health) ──

def _inject_api_key(html: str) -> str:
    """Inject the API key into dashboard HTML so JS can authenticate."""
    return html.replace("<script>\nconst API", f"<script>\nconst API_KEY='{API_SECRET_KEY}';\nconst API", 1)


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


# ── Health (no auth) ──
app.include_router(health.router)

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
app.include_router(brain.router, prefix="/api/v1", dependencies=_viewer)
