"""
Risk Assessment Schema
======================
Module 4 — Hype detection, illiquidity risk, and composite risk scoring.
Each entity gets one RiskAssessment row, updated daily.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class RiskAssessmentBase(SQLModel):
    entity_id: str = Field(index=True, unique=True)

    # Hype vs Reality (0.0 = no hype, 1.0 = pure vaporware)
    hype_score: float = Field(default=0.0)
    substance_score: float = Field(default=0.0)
    hype_gap: float = Field(default=0.0)  # hype - substance (>0.3 = red flag)
    hype_flag: bool = Field(default=False)

    # Illiquidity Risk (0.0 = liquid/safe, 1.0 = critical risk)
    illiquidity_score: float = Field(default=0.0)
    runway_risk: float = Field(default=0.0)
    funding_stale_months: Optional[float] = Field(default=None)
    market_freeze_exposure: float = Field(default=0.0)
    illiquidity_flag: bool = Field(default=False)

    # Concentration Risk
    signal_concentration: float = Field(default=0.0)  # Over-reliance on single source
    sector_crowding: float = Field(default=0.0)        # Too many competitors

    # Composite Risk Score (0.0 = safe, 1.0 = max risk)
    risk_score: float = Field(default=0.0)
    risk_tier: str = Field(default="unassessed")  # GREEN/YELLOW/ORANGE/RED
    risk_flags: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    risk_notes: Optional[str] = Field(default=None)

    # Raw data
    raw_risk_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class RiskAssessment(RiskAssessmentBase, table=True):
    __tablename__ = "risk_assessments"
    id: str = Field(default_factory=_new_id, primary_key=True)
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RiskAssessmentCreate(RiskAssessmentBase):
    pass


class RiskAssessmentRead(RiskAssessmentBase):
    id: str
    assessed_at: datetime
    updated_at: datetime
