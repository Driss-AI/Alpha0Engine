"""
Ticker Timeline Schema
======================
Event timeline for a public ticker.
"""
from typing import Optional, Dict, Any
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


TIMELINE_EVENT_TYPES = ["filing", "signal", "score_change", "catalyst"]


class TickerTimelineBase(SQLModel):
    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True, max_length=30)
    event_title: str
    event_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    event_date: date = Field(index=True)
    source: Optional[str] = Field(default=None, max_length=30)


class TickerTimeline(TickerTimelineBase, table=True):
    __tablename__ = "ticker_timeline"

    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class TickerTimelineCreate(TickerTimelineBase):
    pass


class TickerTimelineRead(TickerTimelineBase):
    id: str
    created_at: datetime
