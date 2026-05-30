"""
Candidate Lane Schema — Sprint 7.2

Many-to-many between `equity_screens` (candidates) and theme lanes. One row per
(candidate, lane) the company matched. A single company can sit in multiple lanes
(e.g. IREN = AI-infra power AND, once L3 is active, crypto-miner pivot).

`bottleneck_exposure` records WHICH bottleneck(s) within the lane the company sits
on (e.g. "power", "optical_networking") — used by the thesis engine (S9) to write
the "Bottleneck:" line and by per-lane backtests (S10).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


class CandidateLane(SQLModel, table=True):
    __tablename__ = "candidate_lanes"
    __table_args__ = (
        UniqueConstraint("entity_id", "lane_id", name="uq_candidate_lane"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)

    # Link to the screened candidate. We key on entity_id (stable) rather than
    # the equity_screens row id (which can be replaced on re-score).
    entity_id: str = Field(index=True, max_length=64)
    ticker: Optional[str] = Field(default=None, index=True, max_length=10)

    lane_id: str = Field(index=True, max_length=40)   # e.g. "L1_AI_INFRA"

    # 0.0–1.0 keyword-density match score at assignment time.
    lane_score: float = Field(default=0.0)

    # Which bottleneck(s) within the lane this company sits on.
    bottleneck_exposure: list = Field(default_factory=list, sa_column=Column(JSON))

    assigned_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
