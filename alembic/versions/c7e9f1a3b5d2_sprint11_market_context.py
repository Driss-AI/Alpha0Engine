"""sprint11 market context signals

Revision ID: c7e9f1a3b5d2
Revises: b2d5f8a3c6e9
Create Date: 2026-05-31

Adds the market_context_signals table (Sprint 11.3) — market-WIDE macro context
(e.g. hyperscaler capex inflection) written by ingest workers and read by the
scoring lenses so the signal actually reaches the score instead of dead-ending.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy import inspect

revision = "c7e9f1a3b5d2"
down_revision = "b2d5f8a3c6e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "market_context_signals" in existing:
        return

    op.create_table(
        "market_context_signals",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("context_type", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column("lane_id", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("period", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("context_type", "period", name="uq_market_context_type_period"),
    )
    # Indexes from the model's index=True flags. Created explicitly here because
    # the table is excluded from the baseline metadata.create_all.
    op.create_index("ix_market_context_signals_context_type", "market_context_signals", ["context_type"])
    op.create_index("ix_market_context_signals_lane_id", "market_context_signals", ["lane_id"])
    op.create_index("ix_market_context_signals_is_active", "market_context_signals", ["is_active"])
    op.create_index("ix_market_context_signals_as_of_date", "market_context_signals", ["as_of_date"])


def downgrade() -> None:
    op.drop_table("market_context_signals")
