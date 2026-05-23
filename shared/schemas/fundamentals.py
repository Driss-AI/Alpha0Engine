"""
Fundamental Score Schema
========================
Module 3 — Moat metrics, proxy valuations, and screening scores.
Each entity gets one FundamentalScore row, updated periodically.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class FundamentalScoreBase(SQLModel):
    entity_id: str = Field(index=True, unique=True)

    # ── Moat Metrics (0.0 – 1.0 each) ──────────────────────
    patent_strength: float = Field(default=0.0)
    ip_breadth: float = Field(default=0.0)
    talent_density: float = Field(default=0.0)
    github_momentum: float = Field(default=0.0)
    competitive_position: float = Field(default=0.0)
    moat_score: float = Field(default=0.0)  # Weighted composite

    # ── Public Equity Metrics ───────────────────────────────
    market_cap_usd: Optional[float] = Field(default=None)
    rd_to_mktcap: Optional[float] = Field(default=None)       # R&D spend / market cap
    gross_margin: Optional[float] = Field(default=None)
    gross_margin_velocity: Optional[float] = Field(default=None)  # QoQ change
    revenue_growth_yoy: Optional[float] = Field(default=None)
    cash_runway_months: Optional[float] = Field(default=None)
    rule_of_40: Optional[float] = Field(default=None)          # Revenue growth + profit margin

    # ── Private Proxy Metrics ───────────────────────────────
    last_round_valuation: Optional[float] = Field(default=None)
    secondary_price: Optional[float] = Field(default=None)
    secondary_vs_primary: Optional[float] = Field(default=None)  # discount/premium %
    estimated_burn_rate: Optional[float] = Field(default=None)   # $/month
    estimated_runway_months: Optional[float] = Field(default=None)
    total_raised: Optional[float] = Field(default=None)
    form_d_total: Optional[float] = Field(default=None)

    # ── Composite Screening Score ───────────────────────────
    fundamental_score: float = Field(default=0.0)  # 0.0 – 1.0
    screening_tier: str = Field(default="unscored")  # S/A/B/C/D
    screening_notes: Optional[str] = Field(default=None)

    # ── Raw data for audit ──────────────────────────────────
    raw_metrics: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class FundamentalScore(FundamentalScoreBase, table=True):
    __tablename__ = "fundamental_scores"
    id: str = Field(default_factory=_new_id, primary_key=True)
    scored_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FundamentalScoreCreate(FundamentalScoreBase):
    pass


class FundamentalScoreRead(FundamentalScoreBase):
    id: str
    scored_at: datetime
    updated_at: datetime
