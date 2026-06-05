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
    # Baseline = the ORIGINAL (pre-Sprint-2) schema.
    #   - Existing databases: stamp this revision with `alembic stamp head`.
    #   - Fresh databases: create only the original tables here, then let the
    #     LATER migrations add their own objects on top.
    #
    # SQLModel.metadata reflects the *current* models, which already include
    # tables/columns introduced by later migrations. If we created all of them
    # here, those later migrations would collide (DuplicateTableError /
    # DuplicateColumn) on a from-scratch `alembic upgrade head`. So we exclude
    # the later-owned tables and strip the later-added signals columns.
    bind = op.get_bind()
    md = SQLModel.metadata

    # Tables created by later migrations (must NOT be created by the baseline):
    later_owned_tables = {
        "brain_opportunities", "brain_narratives", "company_news",  # a1b2c3d4e5f6
        "ingestion_runs",                                            # b2c3d4e5f6a7
        "score_validations",                                         # c3d4e5f6a7b8
        "data_freshness",                                            # d4f6a8b1c2e3
        "candidate_lanes",                                           # e5a7b2c9d1f4
        "clinical_trials", "fda_events", "hyperscaler_capex",        # f6b8c3d2e9a1
        "evidence_items", "alerts",                                  # a1c4e7f9b2d6
        "market_context_signals",                                    # c7e9f1a3b5d2
    }
    baseline_tables = [
        tbl for name, tbl in md.tables.items() if name not in later_owned_tables
    ]
    md.create_all(bind, tables=baseline_tables)

    # The live Signal model already declares `resolution_status` and the
    # `uq_signal_source_type` unique constraint — both ADDED by b2c3d4e5f6a7.
    # Remove them so the baseline matches the original schema and b2c3 can add
    # them cleanly. Guarded so this is a no-op if they are somehow absent.
    insp = sa.inspect(bind)
    if insp.has_table("signals"):
        uq_names = {uc["name"] for uc in insp.get_unique_constraints("signals")}
        if "uq_signal_source_type" in uq_names:
            op.drop_constraint("uq_signal_source_type", "signals", type_="unique")
        col_names = {c["name"] for c in insp.get_columns("signals")}
        if "resolution_status" in col_names:
            op.drop_column("signals", "resolution_status")

    # equity_screens gained 5-axis + bucket columns in a1c4e7f9b2d6. The live
    # model includes them so create_all adds them here — strip them so that
    # migration can add them cleanly on a from-scratch roundtrip. Guarded.
    if insp.has_table("equity_screens"):
        es_cols = {c["name"] for c in insp.get_columns("equity_screens")}
        for later_col in ("best_lane_id", "opportunity_score", "risk_score",
                          "timing_score", "confidence_score", "tradability_score",
                          "bucket"):
            if later_col in es_cols:
                op.drop_column("equity_screens", later_col)

    # score_snapshots gained lane_id in b2d5f8a3c6e9 (same baseline-table pattern).
    if insp.has_table("score_snapshots"):
        ss_cols = {c["name"] for c in insp.get_columns("score_snapshots")}
        if "lane_id" in ss_cols:
            op.drop_column("score_snapshots", "lane_id")


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)
