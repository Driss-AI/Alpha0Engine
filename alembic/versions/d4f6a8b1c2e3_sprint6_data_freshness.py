"""Sprint 6.4: data_freshness table for per-source ingestion health

Revision ID: d4f6a8b1c2e3
Revises: c3d4e5f6a7b8
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f6a8b1c2e3"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: `index=True` on the status Column already creates `ix_data_freshness_status`
    # via op.create_table — do NOT add a separate op.create_index for it (DuplicateTable).
    op.create_table(
        "data_freshness",
        sa.Column("source", sa.String(60), primary_key=True),
        sa.Column("last_successful_run", sa.DateTime(), nullable=True),
        sa.Column("last_attempt", sa.DateTime(), nullable=True),
        sa.Column("records_added_last_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown", index=True),
        sa.Column("freshness_threshold_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    # The status index was created via Column(index=True), so it's auto-dropped
    # when the table is dropped — no separate op.drop_index needed.
    op.drop_table("data_freshness")
