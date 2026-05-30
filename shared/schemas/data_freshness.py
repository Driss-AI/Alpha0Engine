"""
Data Freshness Schema — Sprint 6.4

One row per ingestion source. Updated by `RunTracker.finish()` on every worker run.
Surfaces "is the data current?" without having to scan `ingestion_runs`.

Status semantics:
    fresh    — last successful run within freshness threshold (per-source default 24h)
    stale    — successful but older than threshold
    failing  — consecutive_failures > 0 (last run errored)
    unknown  — no runs recorded yet

The endpoint `/api/v1/data-freshness` returns the full table; the dashboard can
colour-code red/yellow/green tiles directly from `status`.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class DataFreshness(SQLModel, table=True):
    __tablename__ = "data_freshness"

    # source = the service_name from RunTracker (one row per source)
    source: str = Field(primary_key=True, max_length=60)

    last_successful_run: Optional[datetime] = None
    last_attempt: Optional[datetime] = None
    records_added_last_run: int = Field(default=0)
    consecutive_failures: int = Field(default=0)

    # fresh | stale | failing | unknown
    status: str = Field(default="unknown", max_length=20, index=True)

    # informational — per-source freshness threshold in minutes. Default 1440 (24h).
    freshness_threshold_minutes: int = Field(default=1440)

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
