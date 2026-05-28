"""
Brain Opportunity Schema
========================
The AI Brain's daily picks — asymmetric opportunities (10x-1000x potential).
Each row is a fully evidence-backed thesis with upside/downside scenarios,
price targets, catalysts, and citations to source signals.

conviction: HIGH / MEDIUM / LOW
status: active / expired / hit / miss
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class BrainOpportunityBase(SQLModel):
    entity_id: str = Field(index=True)
    ticker: Optional[str] = Field(default=None, index=True)
    company_name: Optional[str] = Field(default=None)
    sector: Optional[str] = Field(default=None)
    market_cap_usd: Optional[float] = Field(default=None)

    # ── Core Thesis ─────────────────────────────────────────
    thesis: str = Field(description="One-paragraph investment thesis")
    narrative: str = Field(description="Full AI-generated narrative with evidence citations")
    thesis_type: Optional[str] = Field(default=None)  # catalyst/earnings/demand/float/convergence

    # ── Scenarios ───────────────────────────────────────────
    upside_scenario: Optional[str] = Field(default=None)
    downside_scenario: Optional[str] = Field(default=None)
    price_current: Optional[float] = Field(default=None)
    price_target_bull: Optional[float] = Field(default=None)
    price_target_bear: Optional[float] = Field(default=None)
    return_multiple: Optional[float] = Field(default=None)  # e.g. 10.0 = 10x potential

    # ── Conviction & Scoring ────────────────────────────────
    conviction: str = Field(default="LOW")  # HIGH / MEDIUM / LOW
    confidence_score: float = Field(default=0.0)  # 0.0-1.0
    signal_count: int = Field(default=0)
    source_diversity: int = Field(default=0)  # number of distinct data sources
    lenses_active: int = Field(default=0)  # how many screener lenses fired (0-5)

    # ── Catalysts & Timeline ────────────────────────────────
    catalysts: List[Dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="List of upcoming catalysts with dates and types",
    )
    time_horizon: Optional[str] = Field(default=None)  # short/medium/long

    # ── Evidence Bundle ─────────────────────────────────────
    key_signals: List[Dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Signal IDs + summaries backing this thesis",
    )
    evidence_sources: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Source names: edgar, clinicaltrials_gov, etc.",
    )

    # ── Status Tracking ─────────────────────────────────────
    status: str = Field(default="active", index=True)  # active/expired/hit/miss
    expires_at: Optional[datetime] = Field(default=None)
    screening_notes: Optional[str] = Field(default=None)

    # ── Feedback / Performance Tracking ─────────────────────
    price_at_pick: Optional[float] = Field(default=None)
    price_latest: Optional[float] = Field(default=None)
    return_pct: Optional[float] = Field(default=None)
    resolved_at: Optional[datetime] = Field(default=None)
    feedback_notes: Optional[str] = Field(default=None)


class BrainOpportunity(BrainOpportunityBase, table=True):
    __tablename__ = "brain_opportunities"
    id: str = Field(default_factory=_new_id, primary_key=True)
    generated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrainOpportunityCreate(BrainOpportunityBase):
    pass


class BrainOpportunityRead(BrainOpportunityBase):
    id: str
    generated_at: datetime
    updated_at: datetime
