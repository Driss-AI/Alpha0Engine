"""Sprint 8: lane data source tables (clinical_trials, fda_events, hyperscaler_capex)

Revision ID: f6b8c3d2e9a1
Revises: e5a7b2c9d1f4
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6b8c3d2e9a1"
down_revision: Union[str, None] = "e5a7b2c9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── clinical_trials (8.1) ────────────────────────────────────────────────
    op.create_table(
        "clinical_trials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("nct_id", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("phase", sa.String(30), nullable=True),
        sa.Column("status", sa.String(40), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("intervention", sa.String(), nullable=True),
        sa.Column("primary_endpoint", sa.String(), nullable=True),
        sa.Column("primary_completion_date", sa.Date(), nullable=True),
        sa.Column("study_completion_date", sa.Date(), nullable=True),
        sa.Column("last_update", sa.Date(), nullable=True),
        sa.Column("catalyst_proximity_days", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("nct_id", "entity_id", name="uq_trial_entity"),
    )
    op.create_index("ix_clinical_trials_nct_id", "clinical_trials", ["nct_id"])
    op.create_index("ix_clinical_trials_entity_id", "clinical_trials", ["entity_id"])
    op.create_index("ix_clinical_trials_ticker", "clinical_trials", ["ticker"])
    op.create_index("ix_clinical_trials_primary_completion_date", "clinical_trials", ["primary_completion_date"])

    # ── fda_events (8.2) ─────────────────────────────────────────────────────
    op.create_table(
        "fda_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("drug_name", sa.String(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("indication", sa.String(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_type", "drug_name", "company", "event_date", name="uq_fda_event"),
    )
    op.create_index("ix_fda_events_event_type", "fda_events", ["event_type"])
    op.create_index("ix_fda_events_drug_name", "fda_events", ["drug_name"])
    op.create_index("ix_fda_events_company", "fda_events", ["company"])
    op.create_index("ix_fda_events_ticker", "fda_events", ["ticker"])
    op.create_index("ix_fda_events_entity_id", "fda_events", ["entity_id"])
    op.create_index("ix_fda_events_event_date", "fda_events", ["event_date"])

    # ── hyperscaler_capex (8.4) ──────────────────────────────────────────────
    op.create_table(
        "hyperscaler_capex",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("fiscal_period", sa.String(10), nullable=False),
        sa.Column("capex_usd", sa.Float(), nullable=True),
        sa.Column("capex_yoy_pct", sa.Float(), nullable=True),
        sa.Column("gpu_spend_disclosed_usd", sa.Float(), nullable=True),
        sa.Column("datacenter_mw_added", sa.Float(), nullable=True),
        sa.Column("is_inflection", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partners_mentioned", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "fiscal_period", name="uq_capex_ticker_period"),
    )
    op.create_index("ix_hyperscaler_capex_ticker", "hyperscaler_capex", ["ticker"])
    op.create_index("ix_hyperscaler_capex_fiscal_period", "hyperscaler_capex", ["fiscal_period"])
    op.create_index("ix_hyperscaler_capex_is_inflection", "hyperscaler_capex", ["is_inflection"])


def downgrade() -> None:
    op.drop_table("hyperscaler_capex")
    op.drop_table("fda_events")
    op.drop_table("clinical_trials")
