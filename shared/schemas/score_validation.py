"""
Score Validation Schema
=======================
Tracks expected vs actual outcomes for scoring calibration.
Each row records a snapshot's prediction and the actual price return
measured at 30/90/180/365 day horizons.
"""
from typing import Optional, Dict, Any
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, UniqueConstraint
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class ScoreValidationBase(SQLModel):
    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True)
    snapshot_date: date = Field(index=True)
    lane_id: Optional[str] = Field(default=None, index=True, max_length=40)  # S10 per-lane backtest

    # Score at time of prediction
    composite_score: float
    conviction_tier: str = Field(max_length=20)
    active_lenses: int = Field(default=0)
    catalyst_score: Optional[float] = None
    earnings_score: Optional[float] = None
    demand_score: Optional[float] = None
    float_score: Optional[float] = None
    smart_money_score: Optional[float] = None
    top_lens: Optional[str] = None

    # Price at snapshot
    price_at_snapshot: Optional[float] = None

    # Actual returns measured later (filled incrementally as time passes)
    return_30d: Optional[float] = None
    return_90d: Optional[float] = None
    return_180d: Optional[float] = None
    return_365d: Optional[float] = None

    price_30d: Optional[float] = None
    price_90d: Optional[float] = None
    price_180d: Optional[float] = None
    price_365d: Optional[float] = None

    # Max drawdown and max gain within each window
    max_drawdown_30d: Optional[float] = None
    max_gain_30d: Optional[float] = None
    max_drawdown_90d: Optional[float] = None
    max_gain_90d: Optional[float] = None

    # Outcome classification
    outcome_30d: Optional[str] = None   # win/loss/flat
    outcome_90d: Optional[str] = None
    outcome_180d: Optional[str] = None
    outcome_365d: Optional[str] = None

    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ScoreValidation(ScoreValidationBase, table=True):
    __tablename__ = "score_validations"
    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_validation_ticker_date"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class ScoreValidationRead(ScoreValidationBase):
    id: str
    created_at: datetime
    updated_at: datetime
