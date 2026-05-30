"""Sprint 9: evidence_items table + multi-axis/bucket columns on equity_screens

Revision ID: a1c4e7f9b2d6
Revises: f6b8c3d2e9a1
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4e7f9b2d6"
down_revision: Union[str, None] = "f6b8c3d2e9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── evidence_items (9.1) ─────────────────────────────────────────────────
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("lane_id", sa.String(40), nullable=True),
        sa.Column("signal_id", sa.String(), nullable=True),
        sa.Column("lens", sa.String(30), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "lane_id", "source_url", name="uq_evidence"),
    )
    op.create_index("ix_evidence_items_entity_id", "evidence_items", ["entity_id"])
    op.create_index("ix_evidence_items_ticker", "evidence_items", ["ticker"])
    op.create_index("ix_evidence_items_lane_id", "evidence_items", ["lane_id"])
    op.create_index("ix_evidence_items_signal_id", "evidence_items", ["signal_id"])

    # ── alerts (9.6, extended in S10.3) ──────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("lane_id", sa.String(40), nullable=True),
        sa.Column("bucket", sa.String(20), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("timing_score", sa.Float(), nullable=True),
        sa.Column("why_now", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("forward_return_7d", sa.Float(), nullable=True),
        sa.Column("forward_return_30d", sa.Float(), nullable=True),
        sa.Column("forward_return_90d", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("was_tradable", sa.Boolean(), nullable=True),
        sa.Column("my_action", sa.String(20), nullable=True),
        sa.Column("outcome_notes", sa.String(), nullable=True),
    )
    op.create_index("ix_alerts_ticker", "alerts", ["ticker"])
    op.create_index("ix_alerts_entity_id", "alerts", ["entity_id"])
    op.create_index("ix_alerts_lane_id", "alerts", ["lane_id"])
    op.create_index("ix_alerts_bucket", "alerts", ["bucket"])
    op.create_index("ix_alerts_delivered", "alerts", ["delivered"])
    op.create_index("ix_alerts_sent_at", "alerts", ["sent_at"])

    # ── equity_screens: 5-axis + bucket (9.4) ────────────────────────────────
    op.add_column("equity_screens", sa.Column("best_lane_id", sa.String(40), nullable=True))
    op.add_column("equity_screens", sa.Column("opportunity_score", sa.Float(), nullable=True))
    op.add_column("equity_screens", sa.Column("risk_score", sa.Float(), nullable=True))
    op.add_column("equity_screens", sa.Column("timing_score", sa.Float(), nullable=True))
    op.add_column("equity_screens", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column("equity_screens", sa.Column("tradability_score", sa.Float(), nullable=True))
    op.add_column("equity_screens", sa.Column("bucket", sa.String(20), nullable=True))
    op.create_index("ix_equity_screens_bucket", "equity_screens", ["bucket"])
    op.create_index("ix_equity_screens_best_lane_id", "equity_screens", ["best_lane_id"])


def downgrade() -> None:
    op.drop_index("ix_equity_screens_best_lane_id", table_name="equity_screens")
    op.drop_index("ix_equity_screens_bucket", table_name="equity_screens")
    for col in ("bucket", "tradability_score", "confidence_score", "timing_score",
                "risk_score", "opportunity_score", "best_lane_id"):
        op.drop_column("equity_screens", col)
    op.drop_table("alerts")
    op.drop_table("evidence_items")
