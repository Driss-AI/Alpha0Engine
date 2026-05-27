"""
Catalyst Event Schema
=====================
Unified catalyst calendar for automated and user-pinned events.
"""
from typing import Optional, Dict, Any
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


CATALYST_TYPES = ["earnings", "fda", "trial", "merger", "lockup", "custom"]
CATALYST_STATUSES = ["upcoming", "passed", "confirmed"]


class CatalystEventBase(SQLModel):
    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True)
    catalyst_type: str = Field(index=True, max_length=30)
    title: str
    expected_date: Optional[date] = Field(default=None, index=True)
    actual_date: Optional[date] = Field(default=None)
    status: str = Field(default="upcoming", index=True, max_length=20)
    impact_score: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    user_pinned: bool = Field(default=False, index=True)


class CatalystEvent(CatalystEventBase, table=True):
    __tablename__ = "catalyst_events"

    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CatalystEventCreate(CatalystEventBase):
    pass


class CatalystEventRead(CatalystEventBase):
    id: str
    created_at: datetime


class CatalystEventUpdate(SQLModel):
    catalyst_type: Optional[str] = None
    title: Optional[str] = None
    expected_date: Optional[date] = None
    actual_date: Optional[date] = None
    status: Optional[str] = None
    impact_score: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    user_pinned: Optional[bool] = None
