"""Sprint 10: lane_id on score_snapshots + score_validations for per-lane backtest

Revision ID: b2d5f8a3c6e9
Revises: a1c4e7f9b2d6
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d5f8a3c6e9"
down_revision: Union[str, None] = "a1c4e7f9b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("score_snapshots", sa.Column("lane_id", sa.String(40), nullable=True))
    op.create_index("ix_score_snapshots_lane_id", "score_snapshots", ["lane_id"])

    op.add_column("score_validations", sa.Column("lane_id", sa.String(40), nullable=True))
    op.create_index("ix_score_validations_lane_id", "score_validations", ["lane_id"])


def downgrade() -> None:
    op.drop_index("ix_score_validations_lane_id", table_name="score_validations")
    op.drop_column("score_validations", "lane_id")
    op.drop_index("ix_score_snapshots_lane_id", table_name="score_snapshots")
    op.drop_column("score_snapshots", "lane_id")
