"""
FDA Event Schema — Sprint 8.2 (L2 Biotech lane)

One row per FDA regulatory event: PDUFA dates, AdCom meetings, approvals, CRLs.
Populated by ingest-fda (FDA approvals RSS, AdCom calendar, OpenFDA).
Drives `pdufa_date` / `adcom_date` / `fda_approval` / `crl` catalyst_events.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


# event_type vocabulary
FDA_EVENT_TYPES = ["pdufa", "adcom", "approval", "crl", "fast_track", "breakthrough"]


class FDAEvent(SQLModel, table=True):
    __tablename__ = "fda_events"
    __table_args__ = (
        # Dedupe identical events (same drug+company+type+date).
        UniqueConstraint("event_type", "drug_name", "company", "event_date",
                         name="uq_fda_event"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)

    event_type: str = Field(index=True, max_length=20)   # see FDA_EVENT_TYPES
    drug_name: Optional[str] = Field(default=None, index=True)
    company: Optional[str] = Field(default=None, index=True)
    ticker: Optional[str] = Field(default=None, index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True, max_length=64)

    indication: Optional[str] = Field(default=None)
    event_date: Optional[date] = Field(default=None, index=True)
    status: Optional[str] = Field(default=None, max_length=40)   # upcoming / approved / rejected

    source_url: Optional[str] = Field(default=None)
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
