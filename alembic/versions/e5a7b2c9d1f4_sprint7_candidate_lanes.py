"""Sprint 7.2: candidate_lanes table (theme-lane assignment)

Revision ID: e5a7b2c9d1f4
Revises: d4f6a8b1c2e3
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a7b2c9d1f4"
down_revision: Union[str, None] = "d4f6a8b1c2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_lanes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("lane_id", sa.String(40), nullable=False),
        sa.Column("lane_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("bottleneck_exposure", sa.JSON(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "lane_id", name="uq_candidate_lane"),
    )
    op.create_index("ix_candidate_lanes_entity_id", "candidate_lanes", ["entity_id"])
    op.create_index("ix_candidate_lanes_ticker", "candidate_lanes", ["ticker"])
    op.create_index("ix_candidate_lanes_lane_id", "candidate_lanes", ["lane_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_lanes_lane_id", table_name="candidate_lanes")
    op.drop_index("ix_candidate_lanes_ticker", table_name="candidate_lanes")
    op.drop_index("ix_candidate_lanes_entity_id", table_name="candidate_lanes")
    op.drop_table("candidate_lanes")
