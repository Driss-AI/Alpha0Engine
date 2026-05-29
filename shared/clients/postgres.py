"""
PostgreSQL Async Client
=======================
Shared async DB client. Import from here — never create separate engines.
"""
import os
from typing import AsyncGenerator
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker


def _async_url(url: str) -> str:
    url = (
        url
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace("postgres://", "postgresql+asyncpg://")
    )
    # Ensure SSL mode is set for Railway's SSL-enabled Postgres
    if "sslmode=" not in url and "ssl=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}ssl=require"
    return url


DATABASE_URL = os.environ["DATABASE_URL"]
ASYNC_DATABASE_URL = _async_url(DATABASE_URL)

# Pool sizing is env-tunable so each service can match its concurrency profile.
# pool_recycle guards against Railway/Postgres dropping idle connections.
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "1800"))

engine: AsyncEngine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.environ.get("LOG_LEVEL", "INFO") == "DEBUG",
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_db_and_tables() -> None:
    """Create all SQLModel tables. Safe to call on every startup."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def drop_db_and_tables() -> None:
    """Drop all tables. ONLY in test teardown."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


async def check_db_health() -> bool:
    """Lightweight liveness probe — runs `SELECT 1` on a pooled connection."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def pool_stats() -> dict:
    """Snapshot of the connection pool for /metrics and health endpoints."""
    pool = engine.pool
    stats = {"size": POOL_SIZE, "max_overflow": MAX_OVERFLOW}
    for attr in ("checkedin", "checkedout", "overflow"):
        getter = getattr(pool, attr, None)
        if callable(getter):
            try:
                stats[attr] = getter()
            except Exception:
                pass
    return stats
