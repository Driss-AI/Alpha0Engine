"""Restructure: drop private/IPO-thesis tables (see RESTRUCTURE.md).

Drops the tables owned by the removed subsystems:
  - themes / theme_entities  (nlp-engine HDBSCAN clustering)
  - embeddings               (nlp-engine pgvector store)
  - brain_opportunities / brain_narratives (brain LLM analyst)

Downgrade intentionally recreates nothing — restore from the pre-restructure
revision if these subsystems ever come back.

Revision ID: a9d2c4e6f8b1
Revises: c7e9f1a3b5d2
"""
from alembic import op

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
    raise RuntimeError(
        "Irreversible: restore dropped tables from revision c7e9f1a3b5d2 "
        "(pre-restructure) instead."
    )
