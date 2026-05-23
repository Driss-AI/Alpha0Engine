"""
Alpha0Engine — FastAPI Gateway v0.2.1
All client-facing endpoints.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()

from shared.clients.postgres import create_db_and_tables
from routers import health, entities, signals, themes, ipo, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(
    title="Alpha0Engine API",
    description="Asymmetric return screening engine — pre-IPO to early public market intelligence.",
    version="0.2.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(entities.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
app.include_router(themes.router, prefix="/api/v1")
app.include_router(ipo.router, prefix="/api/v1")
