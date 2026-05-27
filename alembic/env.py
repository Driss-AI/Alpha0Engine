import os
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

from dotenv import load_dotenv
load_dotenv()

# Import every SQLModel table so metadata.tables is fully populated
from shared.schemas.entities import Entity  # noqa: F401
from shared.schemas.signals import Signal  # noqa: F401
from shared.schemas.themes import Theme, ThemeEntity  # noqa: F401
from shared.schemas.fundamentals import FundamentalScore  # noqa: F401
from shared.schemas.equity_screen import EquityScreen  # noqa: F401
from shared.schemas.risk import RiskAssessment  # noqa: F401
from shared.schemas.daily_prices import DailyPrice  # noqa: F401
from shared.schemas.embeddings import Embedding  # noqa: F401
from shared.schemas.pipeline_health import PipelineHealth  # noqa: F401
from shared.schemas.watchlist import UserWatchlist  # noqa: F401
from shared.schemas.ticker_timeline import TickerTimeline  # noqa: F401
from shared.schemas.score_snapshot import ScoreSnapshot  # noqa: F401
from shared.schemas.catalyst_event import CatalystEvent  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _get_url() -> str:
    url = os.environ["DATABASE_URL"]
    return (
        url
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace("postgres://", "postgresql+asyncpg://")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
