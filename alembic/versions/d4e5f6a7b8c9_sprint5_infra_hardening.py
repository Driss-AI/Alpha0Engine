"""Sprint 5: infra hardening — pg_trgm fuzzy index + unique indexes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29

- 5.1: pg_trgm extension + GIN trigram index on lower(entities.name) so entity
       resolution scales to 100K+ rows without loading them into memory.
- 5.3: unique indexes (ticker, snapshot_date) on score_snapshots and (ticker)
       on user_watchlist. Existing duplicate rows are de-duplicated first
       (keeping the most recent) so the index can be created.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 5.1 pg_trgm fuzzy-name index ──────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entities_name_trgm "
        "ON entities USING gin (lower(name) gin_trgm_ops)"
    )

    # ── 5.3 unique index on score_snapshots(ticker, snapshot_date) ─
    # De-duplicate first (keep newest by created_at), mirroring the Sprint 2
    # pattern that prevents a unique-index build from failing on legacy rows.
    op.execute(
        """
        DELETE FROM score_snapshots a
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY ticker, snapshot_date ORDER BY created_at DESC
            ) AS rn
            FROM score_snapshots
        ) b
        WHERE a.id = b.id AND b.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_score_snapshot_ticker_date "
        "ON score_snapshots (ticker, snapshot_date)"
    )

    # ── 5.3 unique index on user_watchlist(ticker) ────────────────
    op.execute(
        """
        DELETE FROM user_watchlist a
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY ticker ORDER BY added_at DESC
            ) AS rn
            FROM user_watchlist
        ) b
        WHERE a.id = b.id AND b.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_watchlist_ticker "
        "ON user_watchlist (ticker)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_user_watchlist_ticker")
    op.execute("DROP INDEX IF EXISTS uq_score_snapshot_ticker_date")
    op.execute("DROP INDEX IF EXISTS ix_entities_name_trgm")
    # pg_trgm extension is left in place — harmless and may be used elsewhere.
