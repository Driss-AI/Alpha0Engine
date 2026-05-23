"""
Alpha0Engine — FastAPI Gateway v0.3.0
Serves API endpoints + web dashboard at root.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
load_dotenv()

from shared.clients.postgres import create_db_and_tables
from routers import health, entities, signals, themes, ipo, dashboard, fundamentals


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(
    title="Alpha0Engine API",
    description="Asymmetric return screening engine — pre-IPO to early public market intelligence.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard at root
DASHBOARD_HTML = Path(__file__).parent / "static" / "dashboard.html"

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve the CEO dashboard."""
    if DASHBOARD_HTML.exists():
        return HTMLResponse(DASHBOARD_HTML.read_text())
    return HTMLResponse("<h1>Alpha0Engine</h1><p>Dashboard loading...</p>")

app.include_router(health.router)
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(entities.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
app.include_router(themes.router, prefix="/api/v1")
app.include_router(ipo.router, prefix="/api/v1")
app.include_router(fundamentals.router, prefix="/api/v1")
