"""
PostgreSQL Async Client
=======================
Shared async DB client. Import from here — never create separate engines.
"""
import os
from typing import AsyncGenerator
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker


def _async_url(url: str) -> str:
    return (
        url
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace("postgres://", "postgresql+asyncpg://")
    )


DATABASE_URL = os.environ["DATABASE_URL"]
ASYNC_DATABASE_URL = _async_url(DATABASE_URL)

engine: AsyncEngine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.environ.get("LOG_LEVEL", "INFO") == "DEBUG",
    pool_size=5,
    max_overflow=10,
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
