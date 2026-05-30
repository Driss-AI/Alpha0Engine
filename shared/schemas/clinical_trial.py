"""
Clinical Trial Schema — Sprint 8.1 (L2 Biotech lane)

One row per (entity, NCT trial) we track. Populated by ingest-trials from
ClinicalTrials.gov. Feeds the binary-catalyst lens with real catalyst dates
and drives `trial_readout` / `phase_advance` catalyst_events.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


class ClinicalTrial(SQLModel, table=True):
    __tablename__ = "clinical_trials"
    __table_args__ = (
        UniqueConstraint("nct_id", "entity_id", name="uq_trial_entity"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)

    nct_id: str = Field(index=True, max_length=20)
    entity_id: Optional[str] = Field(default=None, index=True, max_length=64)
    ticker: Optional[str] = Field(default=None, index=True, max_length=10)
    company: Optional[str] = Field(default=None)

    phase: Optional[str] = Field(default=None, max_length=30)         # PHASE2 / PHASE3 / ...
    status: Optional[str] = Field(default=None, max_length=40)        # RECRUITING / COMPLETED / ...
    condition: Optional[str] = Field(default=None)
    intervention: Optional[str] = Field(default=None)
    primary_endpoint: Optional[str] = Field(default=None)

    primary_completion_date: Optional[date] = Field(default=None, index=True)
    study_completion_date: Optional[date] = Field(default=None)
    last_update: Optional[date] = Field(default=None)

    # Days until primary completion (catalyst proximity), computed at ingest.
    catalyst_proximity_days: Optional[int] = Field(default=None)

    source_url: Optional[str] = Field(default=None)
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
