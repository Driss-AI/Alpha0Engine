"""Sprint 4: score_validations table for backtest tracking

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "score_validations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False, index=True),
        sa.Column("entity_id", sa.String(), nullable=True, index=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False, index=True),
        # Score at prediction time
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("conviction_tier", sa.String(20), nullable=False),
        sa.Column("active_lenses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("catalyst_score", sa.Float(), nullable=True),
        sa.Column("earnings_score", sa.Float(), nullable=True),
        sa.Column("demand_score", sa.Float(), nullable=True),
        sa.Column("float_score", sa.Float(), nullable=True),
        sa.Column("smart_money_score", sa.Float(), nullable=True),
        sa.Column("top_lens", sa.String(), nullable=True),
        # Price at snapshot
        sa.Column("price_at_snapshot", sa.Float(), nullable=True),
        # Actual returns (filled later)
        sa.Column("return_30d", sa.Float(), nullable=True),
        sa.Column("return_90d", sa.Float(), nullable=True),
        sa.Column("return_180d", sa.Float(), nullable=True),
        sa.Column("return_365d", sa.Float(), nullable=True),
        sa.Column("price_30d", sa.Float(), nullable=True),
        sa.Column("price_90d", sa.Float(), nullable=True),
        sa.Column("price_180d", sa.Float(), nullable=True),
        sa.Column("price_365d", sa.Float(), nullable=True),
        # Drawdown/gain
        sa.Column("max_drawdown_30d", sa.Float(), nullable=True),
        sa.Column("max_gain_30d", sa.Float(), nullable=True),
        sa.Column("max_drawdown_90d", sa.Float(), nullable=True),
        sa.Column("max_gain_90d", sa.Float(), nullable=True),
        # Outcome
        sa.Column("outcome_30d", sa.String(), nullable=True),
        sa.Column("outcome_90d", sa.String(), nullable=True),
        sa.Column("outcome_180d", sa.String(), nullable=True),
        sa.Column("outcome_365d", sa.String(), nullable=True),
        # Meta
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("ticker", "snapshot_date", name="uq_validation_ticker_date"),
    )


def downgrade() -> None:
    op.drop_table("score_validations")
