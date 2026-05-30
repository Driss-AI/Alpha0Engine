"""
Alert Schema — Sprint 9.6 (extended with outcomes in S10.3)

One row per alert dispatched to Telegram. Used for 7-day dedupe (don't re-alert
the same ticker+lane+bucket unless the score moves materially) and, in S10, for
outcome tracking (forward returns vs the alert).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: str = Field(default_factory=_new_id, primary_key=True)

    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True, max_length=64)
    lane_id: Optional[str] = Field(default=None, index=True, max_length=40)
    bucket: str = Field(index=True, max_length=20)          # DEEP_DIVE / SETUP_READY

    # Score snapshot at alert time (for dedupe-on-material-move + S10 analysis).
    composite_score: Optional[float] = Field(default=None)
    opportunity_score: Optional[float] = Field(default=None)
    risk_score: Optional[float] = Field(default=None)
    timing_score: Optional[float] = Field(default=None)

    why_now: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)            # rendered Telegram text
    delivered: bool = Field(default=False, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        index=True,
    )

    # ── S10.3 outcome tracking (filled later by a background job) ───────────
    forward_return_7d: Optional[float] = Field(default=None)
    forward_return_30d: Optional[float] = Field(default=None)
    forward_return_90d: Optional[float] = Field(default=None)
    max_drawdown: Optional[float] = Field(default=None)
    was_tradable: Optional[bool] = Field(default=None)
    my_action: Optional[str] = Field(default=None, max_length=20)  # skipped/watched/dove/bought
    outcome_notes: Optional[str] = Field(default=None)
