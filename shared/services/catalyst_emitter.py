"""
Catalyst emitter (Sprint 8) — shared helper for ingest workers.

Upserts rows into `catalyst_events` with lane-aware typed catalysts. Used by
ingest-trials, ingest-fda, ingest-8k, ingest-news so they all write catalysts
the same way (dedupe on ticker+type+date).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.catalyst_event import CatalystEvent

log = logging.getLogger(__name__)


async def upsert_catalyst(
    session: AsyncSession,
    *,
    ticker: str,
    catalyst_type: str,
    title: str,
    expected_date: Optional[date] = None,
    entity_id: Optional[str] = None,
    status: str = "upcoming",
    impact_score: Optional[float] = None,
    details: Optional[dict[str, Any]] = None,
) -> CatalystEvent:
    """Insert or update a catalyst_events row.

    Dedupe key: (ticker, catalyst_type, expected_date). Re-ingesting the same
    catalyst updates title/status/impact rather than creating duplicates.
    Does NOT commit — the caller owns the transaction.
    """
    existing = (await session.execute(
        select(CatalystEvent).where(
            CatalystEvent.ticker == ticker,
            CatalystEvent.catalyst_type == catalyst_type,
            CatalystEvent.expected_date == expected_date,
        )
    )).scalar_one_or_none()

    if existing is not None:
        existing.title = title
        existing.status = status
        if impact_score is not None:
            existing.impact_score = impact_score
        if details:
            existing.details = {**(existing.details or {}), **details}
        if entity_id and not existing.entity_id:
            existing.entity_id = entity_id
        session.add(existing)
        return existing

    row = CatalystEvent(
        ticker=ticker,
        entity_id=entity_id,
        catalyst_type=catalyst_type,
        title=title,
        expected_date=expected_date,
        status=status,
        impact_score=impact_score,
        details=details or {},
        user_pinned=False,
    )
    session.add(row)
    return row
