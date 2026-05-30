"""
Equity Screen Schema
====================
Module 5 — 1000x Public Equity Screener.
Five scoring lenses: Binary Catalyst, Earnings Inflection, Structural Demand,
Float Mechanics, Smart Money Accumulation.

Each public entity gets one EquityScreen row, updated daily.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class EquityScreenBase(SQLModel):
    entity_id: str = Field(index=True, unique=True)
    ticker: Optional[str] = Field(default=None, index=True)
    company_name: Optional[str] = Field(default=None)
    cik: Optional[str] = Field(default=None, index=True)

    # ── Market Data ─────────────────────────────────────────
    market_cap_usd: Optional[float] = Field(default=None)
    shares_outstanding: Optional[float] = Field(default=None)
    float_shares: Optional[float] = Field(default=None)
    short_interest: Optional[float] = Field(default=None)
    short_pct_float: Optional[float] = Field(default=None)

    # ── Lens 1: Binary Catalyst (SPRB pattern) ──────────────
    catalyst_score: float = Field(default=0.0)
    catalyst_type: Optional[str] = Field(default=None)       # FDA/patent/M&A
    catalyst_proximity_days: Optional[int] = Field(default=None)
    catalyst_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # ── Lens 2: Earnings Inflection (SNDK pattern) ──────────
    earnings_score: float = Field(default=0.0)
    eps_trajectory: Optional[str] = Field(default=None)       # accelerating/inflecting/declining
    quarters_to_profit: Optional[int] = Field(default=None)
    revenue_acceleration: Optional[float] = Field(default=None)
    margin_expansion_rate: Optional[float] = Field(default=None)
    earnings_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # ── Lens 3: Structural Demand Rider ─────────────────────
    demand_score: float = Field(default=0.0)
    megatrend_alignment: Optional[str] = Field(default=None)  # AI/defense/energy/reshoring
    theme_strength: Optional[float] = Field(default=None)
    institutional_neglect: Optional[float] = Field(default=None)  # 0=well-covered, 1=invisible
    demand_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # ── Lens 4: Float Mechanics ─────────────────────────────
    float_score: float = Field(default=0.0)
    float_category: Optional[str] = Field(default=None)       # nano/micro/small/normal
    squeeze_potential: Optional[float] = Field(default=None)   # 0.0-1.0
    days_to_cover: Optional[float] = Field(default=None)
    float_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # ── Lens 5: Smart Money Accumulation ────────────────────
    smart_money_score: float = Field(default=0.0)
    institutional_buys_13f: Optional[int] = Field(default=None)
    insider_buys_form4: Optional[int] = Field(default=None)
    insider_buy_value_usd: Optional[float] = Field(default=None)
    smart_money_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # ── Composite ───────────────────────────────────────────
    composite_score: float = Field(default=0.0)   # 0.0 – 1.0
    conviction_tier: str = Field(default="unscored")  # CONVICTION/HIGH/WATCH/SPECULATIVE/PASS
    active_lenses: int = Field(default=0)  # how many lenses fire (0-5)
    top_lens: Optional[str] = Field(default=None)  # strongest lens
    screening_notes: Optional[str] = Field(default=None)
    on_watchlist: bool = Field(default=False)

    # ── Sprint 9.4: multi-axis scores (0–100) + bucket ──────
    best_lane_id: Optional[str] = Field(default=None, index=True)
    opportunity_score: Optional[float] = Field(default=None)
    risk_score: Optional[float] = Field(default=None)
    timing_score: Optional[float] = Field(default=None)
    confidence_score: Optional[float] = Field(default=None)
    tradability_score: Optional[float] = Field(default=None)
    bucket: Optional[str] = Field(default=None, index=True)  # PASS/WATCH/DEEP_DIVE/SETUP_READY/NO_TOUCH

    # ── Raw data for audit ──────────────────────────────────
    raw_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class EquityScreen(EquityScreenBase, table=True):
    __tablename__ = "equity_screens"
    id: str = Field(default_factory=_new_id, primary_key=True)
    screened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EquityScreenCreate(EquityScreenBase):
    pass


class EquityScreenRead(EquityScreenBase):
    id: str
    screened_at: datetime
    updated_at: datetime
