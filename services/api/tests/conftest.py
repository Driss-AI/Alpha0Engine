import sys
import os
import types
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (PROJECT_ROOT, API_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

engine = create_async_engine("sqlite+aiosqlite://", echo=False)
TestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _get_session():
    async with TestSession() as session:
        yield session


async def _create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def _drop_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


# Stub shared.clients.postgres before any router imports it
_fake_pg = types.ModuleType("shared.clients.postgres")
_fake_pg.get_session = _get_session
_fake_pg.create_db_and_tables = _create_db_and_tables
_fake_pg.drop_db_and_tables = _drop_db_and_tables
_fake_pg.AsyncSessionLocal = TestSession
_fake_pg.engine = engine
sys.modules["shared.clients.postgres"] = _fake_pg

# Stub shared.clients.redis_client
_fake_redis = types.ModuleType("shared.clients.redis_client")
_fake_redis.ping = AsyncMock(return_value="pong")
_fake_redis.get_client = AsyncMock()
sys.modules["shared.clients.redis_client"] = _fake_redis

# Stub shared.clients.heartbeat
_fake_hb = types.ModuleType("shared.clients.heartbeat")
_fake_hb.check_pipeline_health = AsyncMock(return_value=[])
_fake_hb.report_heartbeat = AsyncMock()
sys.modules["shared.clients.heartbeat"] = _fake_hb

# Make shared.clients discoverable as a package-like namespace
if "shared.clients" not in sys.modules:
    _fake_clients = types.ModuleType("shared.clients")
    _fake_clients.__path__ = []
    sys.modules["shared.clients"] = _fake_clients
elif not hasattr(sys.modules["shared.clients"], "__path__"):
    sys.modules["shared.clients"].__path__ = []

from main import app  # noqa: E402

app.dependency_overrides[_get_session] = _get_session


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def session():
    async with TestSession() as s:
        yield s
