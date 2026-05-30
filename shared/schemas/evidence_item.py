"""
Evidence Item Schema — Sprint 9.1

One row per piece of evidence backing a candidate's score in a lane. Every
non-zero lens score must reference >=1 evidence_item in its citation chain, and
the thesis "Evidence:" bullets + the Telegram alert source URLs come from here.

This is what makes an alert defensible: click the URL, see the filing/trial/news.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


# Where the evidence came from.
EVIDENCE_SOURCES = ["sec", "ct_gov", "fda", "form4", "13f", "news", "capex", "transcripts", "prices"]


class EvidenceItem(SQLModel, table=True):
    __tablename__ = "evidence_items"
    __table_args__ = (
        # Dedupe the same source_url for the same candidate+lane.
        UniqueConstraint("entity_id", "lane_id", "source_url", name="uq_evidence"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)

    entity_id: str = Field(index=True, max_length=64)
    ticker: Optional[str] = Field(default=None, index=True, max_length=10)
    lane_id: Optional[str] = Field(default=None, index=True, max_length=40)

    signal_id: Optional[str] = Field(default=None, index=True)
    lens: Optional[str] = Field(default=None, max_length=30)   # which lens this supports
    source: str = Field(max_length=20)                          # see EVIDENCE_SOURCES
    source_url: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)

    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
