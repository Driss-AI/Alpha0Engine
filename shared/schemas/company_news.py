"""
Company News Schema
===================
Financial news articles linked to entities.
Ingested by the news worker, used by the Brain as evidence.
sentiment: bullish / bearish / neutral
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class CompanyNewsBase(SQLModel):
    entity_id: Optional[str] = Field(default=None, index=True)
    ticker: Optional[str] = Field(default=None, index=True)
    company_name: Optional[str] = Field(default=None)

    # ── Article ─────────────────────────────────────────────
    title: str = Field(index=True)
    summary: Optional[str] = Field(default=None)
    url: str = Field(unique=True)
    source: str = Field(index=True)  # reuters, benzinga, seeking_alpha, etc.
    author: Optional[str] = Field(default=None)

    # ── Classification ──────────────────────────────────────
    sentiment: Optional[str] = Field(default=None, index=True)  # bullish/bearish/neutral
    sentiment_score: Optional[float] = Field(default=None)  # -1.0 to +1.0
    relevance_score: Optional[float] = Field(default=None)  # 0.0 to 1.0
    categories: list = Field(default_factory=list, sa_column=Column(JSON))  # earnings, fda, m&a, etc.

    # ── Timestamps ──────────────────────────────────────────
    published_at: Optional[datetime] = Field(default=None, index=True)

    # ── Raw ─────────────────────────────────────────────────
    raw_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class CompanyNews(CompanyNewsBase, table=True):
    __tablename__ = "company_news"
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CompanyNewsCreate(CompanyNewsBase):
    pass


class CompanyNewsRead(CompanyNewsBase):
    id: str
    created_at: datetime
