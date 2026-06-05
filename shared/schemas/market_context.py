"""
Market Context Signal Schema — Sprint 11.3 (Closed-Loop Plumbing)

Market-WIDE context signals (not per-company). These capture macro/sector
conditions that should tilt the score of a whole lane rather than a single
ticker — e.g. a hyperscaler capex inflection lifts demand across the entire
L1 AI-infrastructure supply chain.

Written by ingest workers (e.g. ingest-hyperscaler-capex), read by the scoring
lenses (e.g. lens_demand_rider) so a real macro signal actually reaches the
score instead of sitting in a dead-end table.
"""
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


# Known context types (extend as more macro signals come online).
MARKET_CONTEXT_TYPES = [
    "hyperscaler_capex_inflection",
]


class MarketContextSignalBase(SQLModel):
    context_type: str = Field(index=True, max_length=50)
    lane_id: Optional[str] = Field(default=None, index=True, max_length=40)
    value: float = Field(default=0.0)            # magnitude (e.g. max YoY pct, fraction)
    period: Optional[str] = Field(default=None, max_length=10)   # e.g. "2026Q1"
    source: Optional[str] = Field(default=None, max_length=50)
    is_active: bool = Field(default=True, index=True)
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    as_of_date: date = Field(default_factory=date.today, index=True)


class MarketContextSignal(MarketContextSignalBase, table=True):
    __tablename__ = "market_context_signals"
    __table_args__ = (
        UniqueConstraint("context_type", "period", name="uq_market_context_type_period"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class MarketContextSignalCreate(MarketContextSignalBase):
    pass


class MarketContextSignalRead(MarketContextSignalBase):
    id: str
    created_at: datetime
