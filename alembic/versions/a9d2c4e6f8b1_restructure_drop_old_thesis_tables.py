"""Restructure: drop private/IPO-thesis tables (see RESTRUCTURE.md).

Drops the tables owned by the removed subsystems:
  - themes / theme_entities  (nlp-engine HDBSCAN clustering)
  - embeddings               (nlp-engine store; its vector column was added
                              via raw SQL at runtime, not by migrations)
  - brain_opportunities / brain_narratives (brain LLM analyst)

Downgrade recreates the SCHEMAS (faithful to what the baseline /
a1b2c3d4e5f6 created) so the migration chain stays fully replayable in both
directions — but the dropped DATA is gone; restore from a backup if it
matters.

Revision ID: a9d2c4e6f8b1
Revises: c7e9f1a3b5d2
"""
from alembic import op
import sqlalchemy as sa

revision = "a9d2c4e6f8b1"
down_revision = "c7e9f1a3b5d2"
branch_labels = None
depends_on = None

DROPPED_TABLES = (
    "theme_entities",
    "themes",
    "embeddings",
    "brain_narratives",
    "brain_opportunities",
)


def upgrade() -> None:
    for table in DROPPED_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    # Schema-only recreation (data is not restorable). Shapes mirror the old
    # shared/schemas definitions (themes/embeddings, created by the baseline)
    # and migration a1b2c3d4e5f6 (brain tables).
    op.create_table(
        "themes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("velocity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_similarity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="emerging"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "theme_entities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("theme_id", sa.String(), nullable=False, index=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("similarity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "embeddings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, index=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=False,
                  server_default="all-MiniLM-L6-v2"),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="384"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "brain_opportunities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("ticker", sa.String(), nullable=True, index=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("market_cap_usd", sa.Float(), nullable=True),
        sa.Column("thesis", sa.String(), nullable=False),
        sa.Column("narrative", sa.String(), nullable=False),
        sa.Column("thesis_type", sa.String(), nullable=True),
        sa.Column("upside_scenario", sa.String(), nullable=True),
        sa.Column("downside_scenario", sa.String(), nullable=True),
        sa.Column("price_current", sa.Float(), nullable=True),
        sa.Column("price_target_bull", sa.Float(), nullable=True),
        sa.Column("price_target_bear", sa.Float(), nullable=True),
        sa.Column("return_multiple", sa.Float(), nullable=True),
        sa.Column("conviction", sa.String(), nullable=False, server_default="LOW"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_diversity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lenses_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("catalysts", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("time_horizon", sa.String(), nullable=True),
        sa.Column("key_signals", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("evidence_sources", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="active", index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("screening_notes", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "brain_narratives",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("ticker", sa.String(), nullable=True, index=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("narrative_text", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("key_changes", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("conviction_level", sa.String(), nullable=False, server_default="HOLD"),
        sa.Column("risk_summary", sa.String(), nullable=True),
        sa.Column("bull_case", sa.String(), nullable=True),
        sa.Column("bear_case", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("trigger_signal_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("evidence_bundle", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
