"""Module 2: themes + embeddings tables — Revision 002"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table("themes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("velocity_score", sa.Float(), nullable=False, default=0.0),
        sa.Column("entity_count", sa.Integer(), default=0),
        sa.Column("signal_count", sa.Integer(), default=0),
        sa.Column("avg_similarity", sa.Float(), default=0.0),
        sa.Column("status", sa.String(), default="emerging"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table("theme_entities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("theme_id", sa.String(), nullable=False, index=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("similarity_score", sa.Float(), default=0.0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
    )

    # Embeddings table with pgvector column
    op.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL REFERENCES entities(id),
            text TEXT NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT,
            embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
            dimensions INTEGER DEFAULT 384,
            embedding vector(384),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_entity ON embeddings(entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_source ON embeddings(source)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS embeddings")
    op.drop_table("theme_entities")
    op.drop_table("themes")
