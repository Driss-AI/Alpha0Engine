"""
Signal Schema
=============
Every data point is a Signal. Atomic unit of intelligence.
value: -1.0 bearish to +1.0 bullish
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


SIGNAL_TYPES = [
    "patent_filing", "patent_grant", "form_d",
    "github_commit", "github_star", "job_posting",
    "secondary_trade", "citation", "news_mention", "crossover_filing",
    "clinical_trial", "fda_catalyst",
]

SIGNAL_SOURCES = [
    "uspto", "edgar", "github", "caplight",
    "forge", "hiive", "semantic_scholar", "openalexia",
    "wellfound", "sec_13f", "manual",
    "clinicaltrials_gov", "fda_gov",
]


class SignalBase(SQLModel):
    entity_id: str = Field(index=True)
    signal_type: str = Field(index=True)
    signal_date: datetime = Field(index=True)
    value: float = Field(default=0.0)
    raw_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source: str
    source_id: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)


class Signal(SignalBase, table=True):
    __tablename__ = "signals"
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SignalCreate(SignalBase):
    pass


class SignalRead(SignalBase):
    id: str
    created_at: datetime
