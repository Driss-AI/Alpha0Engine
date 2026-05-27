"""baseline — all existing tables

Revision ID: 3e1718e17ee4
Revises:
Create Date: 2026-05-28 01:22:38.960371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlmodel import SQLModel

# Ensure all table models are registered on SQLModel.metadata
import shared.schemas.entities  # noqa: F401
import shared.schemas.signals  # noqa: F401
import shared.schemas.themes  # noqa: F401
import shared.schemas.fundamentals  # noqa: F401
import shared.schemas.equity_screen  # noqa: F401
import shared.schemas.risk  # noqa: F401
import shared.schemas.daily_prices  # noqa: F401
import shared.schemas.embeddings  # noqa: F401
import shared.schemas.pipeline_health  # noqa: F401
import shared.schemas.watchlist  # noqa: F401
import shared.schemas.ticker_timeline  # noqa: F401
import shared.schemas.score_snapshot  # noqa: F401
import shared.schemas.catalyst_event  # noqa: F401


revision: str = '3e1718e17ee4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All 14 tables defined in shared/schemas/.
    # For existing databases: stamp this revision with `alembic stamp head`.
    # For fresh databases: this creates all tables from SQLModel metadata.
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)
