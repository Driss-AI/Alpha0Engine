"""
Brain Narrative Schema
======================
Per-company AI analysis that updates whenever new data arrives.
A living document: the brain re-evaluates its view on a company
each time fresh signals appear (earnings, FDA update, insider buy, etc.).

conviction_level: STRONG_BUY / BUY / HOLD / CAUTIOUS / AVOID
trigger: what new data caused this narrative to be (re)generated
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class BrainNarrativeBase(SQLModel):
    entity_id: str = Field(index=True)
    ticker: Optional[str] = Field(default=None, index=True)
    company_name: Optional[str] = Field(default=None)

    # ── Narrative Content ───────────────────────────────────
    narrative_text: str = Field(description="Full AI-generated company analysis")
    summary: Optional[str] = Field(default=None, description="2-3 sentence TL;DR")

    # ── Key Changes ─────────────────────────────────────────
    key_changes: List[Dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="What changed since last narrative: [{field, old, new, signal_id}]",
    )

    # ── Assessment ──────────────────────────────────────────
    conviction_level: str = Field(default="HOLD")  # STRONG_BUY/BUY/HOLD/CAUTIOUS/AVOID
    risk_summary: Optional[str] = Field(default=None)
    bull_case: Optional[str] = Field(default=None)
    bear_case: Optional[str] = Field(default=None)

    # ── Trigger ─────────────────────────────────────────────
    trigger: Optional[str] = Field(default=None)  # what data event triggered regeneration
    trigger_signal_ids: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Signal IDs that triggered this narrative update",
    )

    # ── Evidence ────────────────────────────────────────────
    evidence_bundle: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="All evidence cited in narrative: {signal_id: summary}",
    )
    source_count: int = Field(default=0)  # distinct data sources used

    # ── Version ─────────────────────────────────────────────
    version: int = Field(default=1)  # increments on each regeneration


class BrainNarrative(BrainNarrativeBase, table=True):
    __tablename__ = "brain_narratives"
    id: str = Field(default_factory=_new_id, primary_key=True)
    generated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrainNarrativeCreate(BrainNarrativeBase):
    pass


class BrainNarrativeRead(BrainNarrativeBase):
    id: str
    generated_at: datetime
    updated_at: datetime
    version: int
