"""
Lane assignment (Sprint 7.3)

For each scored entity, run the lane keyword/sector/market-cap matchers against
its filings + business description + signal text, and upsert one `candidate_lanes`
row per matched lane.

Runs inside the screener batch (the screener already has entity + signals +
fundamentals loaded, so a separate lane-router service would just re-query).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.lanes import match_lanes
from shared.schemas.candidate_lane import CandidateLane

logger = logging.getLogger(__name__)


def _gather_match_text(entity: Any, signals: list[dict[str, Any]]) -> str:
    """Assemble the text corpus a lane is matched against."""
    parts: list[str] = []
    # Entity-level descriptors
    for attr in ("name", "sector", "subsector", "description", "business_summary"):
        val = getattr(entity, attr, None)
        if val:
            parts.append(str(val))
    # Signal notes + raw data (filings, news, etc.)
    for sig in signals:
        if sig.get("notes"):
            parts.append(str(sig["notes"]))
        raw = sig.get("raw_data") or {}
        if raw:
            parts.append(str(raw))
    return " ".join(parts)


async def assign_lanes(
    session: AsyncSession,
    entity: Any,
    signals: list[dict[str, Any]],
    market_cap_usd: Optional[float],
) -> list[CandidateLane]:
    """Match `entity` to lanes and upsert candidate_lanes rows.

    Returns the list of CandidateLane rows that are now current for this entity.
    Lanes the entity no longer matches are removed.
    """
    text = _gather_match_text(entity, signals)
    matches = match_lanes(
        text=text,
        sector=getattr(entity, "sector", None),
        market_cap_usd=market_cap_usd,
        exchange=getattr(entity, "exchange", None),
    )
    matched_lane_ids = {m.lane_id for m in matches}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Existing rows for this entity
    existing_rows = (await session.exec(
        select(CandidateLane).where(CandidateLane.entity_id == entity.id)
    )).all()
    existing_by_lane = {r.lane_id: r for r in existing_rows}

    current: list[CandidateLane] = []

    # Upsert matches
    for m in matches:
        row = existing_by_lane.get(m.lane_id)
        if row is None:
            row = CandidateLane(
                entity_id=entity.id,
                ticker=getattr(entity, "ticker", None),
                lane_id=m.lane_id,
                lane_score=m.score,
                bottleneck_exposure=m.bottlenecks,
                assigned_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.ticker = getattr(entity, "ticker", None)
            row.lane_score = m.score
            row.bottleneck_exposure = m.bottlenecks
            row.updated_at = now
            session.add(row)
        current.append(row)

    # Remove rows for lanes the entity no longer matches
    for lane_id, row in existing_by_lane.items():
        if lane_id not in matched_lane_ids:
            await session.delete(row)

    return current
