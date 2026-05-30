"""
Score Snapshot Schema
=====================
Daily score snapshots used to compute screener deltas.
"""
from typing import Optional
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class ScoreSnapshotBase(SQLModel):
    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True)
    composite_score: float
    catalyst_score: Optional[float] = None
    earnings_score: Optional[float] = None
    demand_score: Optional[float] = None
    float_score: Optional[float] = None
    smart_money_score: Optional[float] = None
    active_lenses: Optional[int] = None
    conviction_tier: Optional[str] = Field(default=None, index=True, max_length=20)
    lane_id: Optional[str] = Field(default=None, index=True, max_length=40)  # S10 per-lane backtest
    snapshot_date: date = Field(default_factory=date.today, index=True)


class ScoreSnapshot(ScoreSnapshotBase, table=True):
    __tablename__ = "score_snapshots"

    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class ScoreSnapshotCreate(ScoreSnapshotBase):
    pass


class ScoreSnapshotRead(ScoreSnapshotBase):
    id: str
    created_at: datetime
