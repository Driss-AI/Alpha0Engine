"""
Signal Schema
=============
Every data point is a Signal. Atomic unit of intelligence.
value: -1.0 bearish to +1.0 bullish
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, UniqueConstraint
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


# Documentation of the types the live ingesters actually emit (not enforced —
# signal_type is free-form; 8-K catalyst categories are also written directly,
# e.g. fda_approval / merger_acquisition / hyperscaler_contract).
SIGNAL_TYPES = [
    "8k_event", "red_flag",                                    # sec (8-K)
    "insider_buy_cluster", "insider_sell_cluster", "form_4_insider",  # sec (Form 4)
    "institutional_accumulation",                              # sec (13F)
    "clinical_trial", "fda_catalyst",                          # trials / FDA
    "news_mention",                                            # news
    "volume_awakening", "price_breakout", "float_snapshot",    # prices
]

SIGNAL_SOURCES = [
    "edgar_8k", "edgar_form4", "sec_13f",
    "clinicaltrials_gov", "fda_gov",
    "finnhub", "ingest_prices", "manual",
]


RESOLUTION_STATUSES = ["pending", "resolved", "failed"]


class SignalBase(SQLModel):
    entity_id: str = Field(index=True)
    signal_type: str = Field(index=True)
    signal_date: datetime = Field(index=True)
    value: float = Field(default=0.0)
    raw_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source: str
    source_id: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)
    resolution_status: str = Field(default="pending", index=True, max_length=20)


class Signal(SignalBase, table=True):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("source", "source_id", "signal_type", name="uq_signal_source_type"),
    )
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SignalCreate(SignalBase):
    pass


class SignalRead(SignalBase):
    id: str
    created_at: datetime
