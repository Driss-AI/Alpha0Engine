"""add brain_opportunities, brain_narratives, company_news tables

Revision ID: a1b2c3d4e5f6
Revises: 3e1718e17ee4
Create Date: 2026-05-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3e1718e17ee4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── brain_opportunities ─────────────────────────────────
    op.create_table(
        'brain_opportunities',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('entity_id', sa.String(), nullable=False, index=True),
        sa.Column('ticker', sa.String(), nullable=True, index=True),
        sa.Column('company_name', sa.String(), nullable=True),
        sa.Column('sector', sa.String(), nullable=True),
        sa.Column('market_cap_usd', sa.Float(), nullable=True),
        # Core Thesis
        sa.Column('thesis', sa.String(), nullable=False),
        sa.Column('narrative', sa.String(), nullable=False),
        sa.Column('thesis_type', sa.String(), nullable=True),
        # Scenarios
        sa.Column('upside_scenario', sa.String(), nullable=True),
        sa.Column('downside_scenario', sa.String(), nullable=True),
        sa.Column('price_current', sa.Float(), nullable=True),
        sa.Column('price_target_bull', sa.Float(), nullable=True),
        sa.Column('price_target_bear', sa.Float(), nullable=True),
        sa.Column('return_multiple', sa.Float(), nullable=True),
        # Conviction & Scoring
        sa.Column('conviction', sa.String(), nullable=False, server_default='LOW'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('signal_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source_diversity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lenses_active', sa.Integer(), nullable=False, server_default='0'),
        # Catalysts & Timeline
        sa.Column('catalysts', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('time_horizon', sa.String(), nullable=True),
        # Evidence Bundle
        sa.Column('key_signals', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('evidence_sources', sa.JSON(), nullable=True, server_default='[]'),
        # Status Tracking
        sa.Column('status', sa.String(), nullable=False, server_default='active', index=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('screening_notes', sa.String(), nullable=True),
        # Timestamps
        sa.Column('generated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ── brain_narratives ────────────────────────────────────
    op.create_table(
        'brain_narratives',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('entity_id', sa.String(), nullable=False, index=True),
        sa.Column('ticker', sa.String(), nullable=True, index=True),
        sa.Column('company_name', sa.String(), nullable=True),
        # Narrative Content
        sa.Column('narrative_text', sa.String(), nullable=False),
        sa.Column('summary', sa.String(), nullable=True),
        # Key Changes
        sa.Column('key_changes', sa.JSON(), nullable=True, server_default='[]'),
        # Assessment
        sa.Column('conviction_level', sa.String(), nullable=False, server_default='HOLD'),
        sa.Column('risk_summary', sa.String(), nullable=True),
        sa.Column('bull_case', sa.String(), nullable=True),
        sa.Column('bear_case', sa.String(), nullable=True),
        # Trigger
        sa.Column('trigger', sa.String(), nullable=True),
        sa.Column('trigger_signal_ids', sa.JSON(), nullable=True, server_default='[]'),
        # Evidence
        sa.Column('evidence_bundle', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('source_count', sa.Integer(), nullable=False, server_default='0'),
        # Version
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        # Timestamps
        sa.Column('generated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ── company_news ────────────────────────────────────────
    op.create_table(
        'company_news',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('entity_id', sa.String(), nullable=True, index=True),
        sa.Column('ticker', sa.String(), nullable=True, index=True),
        sa.Column('company_name', sa.String(), nullable=True),
        # Article
        sa.Column('title', sa.String(), nullable=False, index=True),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=False, unique=True),
        sa.Column('source', sa.String(), nullable=False, index=True),
        sa.Column('author', sa.String(), nullable=True),
        # Classification
        sa.Column('sentiment', sa.String(), nullable=True, index=True),
        sa.Column('sentiment_score', sa.Float(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('categories', sa.JSON(), nullable=True, server_default='[]'),
        # Timestamps
        sa.Column('published_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        # Raw
        sa.Column('raw_data', sa.JSON(), nullable=True, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_table('company_news')
    op.drop_table('brain_narratives')
    op.drop_table('brain_opportunities')
