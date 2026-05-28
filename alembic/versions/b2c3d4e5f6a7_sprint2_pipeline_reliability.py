"""Sprint 2: pipeline reliability — idempotency, ingestion_runs, resolution_status

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ingestion_runs table
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("service_name", sa.String(50), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, index=True, server_default="running"),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_messages", sa.JSON(), nullable=True),
        sa.Column("run_metadata", sa.JSON(), nullable=True),
    )

    # 2. Add resolution_status column to signals
    op.add_column("signals", sa.Column("resolution_status", sa.String(20), server_default="pending", index=True))

    # Backfill: set existing UNRESOLVED rows to 'pending', others to 'resolved'
    op.execute("UPDATE signals SET resolution_status = 'pending' WHERE entity_id = 'UNRESOLVED'")
    op.execute("UPDATE signals SET resolution_status = 'resolved' WHERE entity_id != 'UNRESOLVED' AND resolution_status IS NULL")

    # 3. Deduplicate existing signals before adding unique constraint.
    # Keep the newest row (by created_at) for each (source, source_id, signal_type) combo.
    op.execute("""
        DELETE FROM signals
        WHERE source_id IS NOT NULL
          AND id NOT IN (
            SELECT DISTINCT ON (source, source_id, signal_type) id
            FROM signals
            WHERE source_id IS NOT NULL
            ORDER BY source, source_id, signal_type, created_at DESC NULLS LAST
          )
    """)

    # 4. Add unique constraint for signal idempotency (source + source_id + signal_type)
    # Only apply to rows where source_id is NOT NULL (many signals have NULL source_id)
    op.create_index(
        "uq_signal_source_type",
        "signals",
        ["source", "source_id", "signal_type"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_signal_source_type", table_name="signals")
    op.drop_column("signals", "resolution_status")
    op.drop_table("ingestion_runs")
