"""Initial schema: entities + signals — Revision 001"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("entities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("domain", sa.String(), nullable=True, index=True),
        sa.Column("cik", sa.String(), nullable=True, index=True),
        sa.Column("ein", sa.String(), nullable=True),
        sa.Column("lei", sa.String(), nullable=True),
        sa.Column("crunchbase_id", sa.String(), nullable=True),
        sa.Column("pitchbook_id", sa.String(), nullable=True),
        sa.Column("github_org", sa.String(), nullable=True, index=True),
        sa.Column("ticker", sa.String(), nullable=True, index=True),
        sa.Column("entity_type", sa.String(), nullable=False, default="private"),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("subsector", sa.String(), nullable=True),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("hq_country", sa.String(), nullable=True),
        sa.Column("hq_city", sa.String(), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resolution_confidence", sa.Float(), nullable=False, default=1.0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table("signals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("signal_type", sa.String(), nullable=False, index=True),
        sa.Column("signal_date", sa.DateTime(), nullable=False, index=True),
        sa.Column("value", sa.Float(), nullable=False, default=0.0),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
    )
    op.create_index("ix_signals_entity_type_date", "signals", ["entity_id", "signal_type", "signal_date"])


def downgrade():
    op.drop_index("ix_signals_entity_type_date", table_name="signals")
    op.drop_table("signals")
    op.drop_table("entities")
