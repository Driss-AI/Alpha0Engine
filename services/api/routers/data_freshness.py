"""
Data Freshness Router — Sprint 6.4

GET /api/v1/data-freshness  → list of all sources with their freshness status.

Computes a derived `staleness_minutes` and refreshes `status` (fresh|stale|failing|unknown)
based on `freshness_threshold_minutes` so the dashboard always sees the current truth
even between worker runs.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from middleware.auth import require_api_key
from shared.clients.postgres import get_session
from shared.schemas.data_freshness import DataFreshness

router = APIRouter(tags=["Health"])


def _staleness_minutes(last_success: Optional[datetime]) -> Optional[int]:
    if last_success is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, int((now - last_success).total_seconds() // 60))


def _derive_status(row: DataFreshness, staleness_min: Optional[int]) -> str:
    if row.consecutive_failures > 0:
        return "failing"
    if staleness_min is None:
        return "unknown"
    return "fresh" if staleness_min <= row.freshness_threshold_minutes else "stale"


@router.get("/data-freshness", dependencies=[Depends(require_api_key)])
async def get_data_freshness(session: AsyncSession = Depends(get_session)):
    """All ingestion sources with their freshness status.

    Returns:
        {
          "sources": [
            {
              "source": "ingest-edgar",
              "status": "fresh" | "stale" | "failing" | "unknown",
              "last_successful_run": "2026-05-30T08:00:00",
              "last_attempt": "2026-05-30T08:00:00",
              "staleness_minutes": 17,
              "consecutive_failures": 0,
              "records_added_last_run": 42,
              "freshness_threshold_minutes": 1440
            },
            ...
          ],
          "summary": {"fresh": 11, "stale": 2, "failing": 1, "unknown": 2, "total": 16}
        }
    """
    rows = (await session.execute(select(DataFreshness).order_by(DataFreshness.source))).scalars().all()

    out = []
    counts = {"fresh": 0, "stale": 0, "failing": 0, "unknown": 0}
    for r in rows:
        staleness = _staleness_minutes(r.last_successful_run)
        status = _derive_status(r, staleness)
        counts[status] = counts.get(status, 0) + 1
        out.append({
            "source": r.source,
            "status": status,
            "last_successful_run": r.last_successful_run.isoformat() if r.last_successful_run else None,
            "last_attempt": r.last_attempt.isoformat() if r.last_attempt else None,
            "staleness_minutes": staleness,
            "consecutive_failures": r.consecutive_failures,
            "records_added_last_run": r.records_added_last_run,
            "freshness_threshold_minutes": r.freshness_threshold_minutes,
        })

    return {"sources": out, "summary": {**counts, "total": len(out)}}
