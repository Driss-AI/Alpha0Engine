"""
Daily Price Schema
==================
Market data backbone — daily OHLCV, market cap, volume metrics.
Every ticker gets one row per trading day.
This is the foundational data layer that makes every scoring lens accurate:
  - Real market cap (not stale XBRL)
  - Price filtering (penny/micro-cap discovery)
  - Volume for days-to-cover (Float Mechanics)
  - Price-volume breakout detection
"""
from typing import Optional, Dict, Any
from datetime import datetime, date
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, UniqueConstraint
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class DailyPriceBase(SQLModel):
    entity_id: Optional[str] = Field(default=None, index=True)
    ticker: str = Field(index=True)
    trade_date: date = Field(index=True)

    # ── OHLCV ───────────────────────────────────────────────
    open: Optional[float] = Field(default=None)
    high: Optional[float] = Field(default=None)
    low: Optional[float] = Field(default=None)
    close: Optional[float] = Field(default=None)
    volume: Optional[float] = Field(default=None)

    # ── Derived ─────────────────────────────────────────────
    market_cap: Optional[float] = Field(default=None)
    shares_outstanding: Optional[float] = Field(default=None)
    avg_volume_10d: Optional[float] = Field(default=None)
    avg_volume_30d: Optional[float] = Field(default=None)

    # ── Change metrics ──────────────────────────────────────
    change_pct: Optional[float] = Field(default=None)       # daily % change
    change_5d_pct: Optional[float] = Field(default=None)     # 5-day % change
    change_20d_pct: Optional[float] = Field(default=None)    # 20-day % change

    # ── Flags ───────────────────────────────────────────────
    is_penny: bool = Field(default=False)     # close < $5
    is_micro: bool = Field(default=False)     # close < $50 and mcap < $500M


class DailyPrice(DailyPriceBase, table=True):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_ticker_date"),
    )
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DailyPriceCreate(DailyPriceBase):
    pass


class DailyPriceRead(DailyPriceBase):
    id: str
    created_at: datetime


# ── Latest price snapshot (non-table model for API) ─────────
class PriceSnapshot(SQLModel):
    ticker: str
    entity_id: Optional[str] = None
    company_name: Optional[str] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    change_pct: Optional[float] = None
    change_5d_pct: Optional[float] = None
    change_20d_pct: Optional[float] = None
    avg_volume_30d: Optional[float] = None
    is_penny: bool = False
    is_micro: bool = False
    trade_date: Optional[date] = None
