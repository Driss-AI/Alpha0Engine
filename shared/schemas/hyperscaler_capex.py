"""
Hyperscaler Capex Schema — Sprint 8.4 (L1 AI Infrastructure lane)

Tracks quarterly capex for the hyperscalers whose spending IS the demand signal
for the AI-infra lane (MSFT, GOOG, META, AMZN, ORCL). A YoY capex inflection is
a leading indicator for the whole power/data-center/optical supply chain.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


HYPERSCALERS = ["MSFT", "GOOGL", "META", "AMZN", "ORCL"]


class HyperscalerCapex(SQLModel, table=True):
    __tablename__ = "hyperscaler_capex"
    __table_args__ = (
        UniqueConstraint("ticker", "fiscal_period", name="uq_capex_ticker_period"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)

    ticker: str = Field(index=True, max_length=10)
    company: Optional[str] = Field(default=None)
    fiscal_period: str = Field(index=True, max_length=10)   # e.g. "2026Q1"

    capex_usd: Optional[float] = Field(default=None)        # quarterly capex
    capex_yoy_pct: Optional[float] = Field(default=None)    # YoY growth (fraction, e.g. 0.34)
    gpu_spend_disclosed_usd: Optional[float] = Field(default=None)
    datacenter_mw_added: Optional[float] = Field(default=None)

    # Inflection flag — set when capex_yoy_pct > 0.30
    is_inflection: bool = Field(default=False, index=True)

    partners_mentioned: list = Field(default_factory=list, sa_column=Column(JSON))
    source_url: Optional[str] = Field(default=None)
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
