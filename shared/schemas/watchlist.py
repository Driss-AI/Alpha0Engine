"""
User Watchlist Schema
=====================
Personal curation layer for Alpha0Engine.
"""
from typing import Optional
from datetime import datetime, date, timezone
from sqlmodel import SQLModel, Field
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


WATCHLIST_PRIORITIES = ["high", "medium", "low"]


class UserWatchlistBase(SQLModel):
    ticker: str = Field(index=True, max_length=10)
    entity_id: Optional[str] = Field(default=None, index=True)
    notes: Optional[str] = Field(default=None)
    priority: str = Field(default="medium", index=True)
    catalyst_date: Optional[date] = Field(default=None, index=True)
    hearted: bool = Field(default=True, index=True)


class UserWatchlist(UserWatchlistBase, table=True):
    __tablename__ = "user_watchlist"

    id: str = Field(default_factory=_new_id, primary_key=True)
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class UserWatchlistCreate(UserWatchlistBase):
    pass


class UserWatchlistRead(UserWatchlistBase):
    id: str
    added_at: datetime
    updated_at: datetime


class UserWatchlistUpdate(SQLModel):
    notes: Optional[str] = None
    priority: Optional[str] = None
    catalyst_date: Optional[date] = None
    hearted: Optional[bool] = None
    entity_id: Optional[str] = None
