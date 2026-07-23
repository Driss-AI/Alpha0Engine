"""Universe ordering helpers for the screener batches.

The product hunts micro-caps, so when a batch is cut short (step timeout,
rate limits, row limits) the smallest companies must have been scored first
— a truncated run should sacrifice the mega-caps, never the hunting ground.
"""
from typing import Dict, Iterable, Sequence

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.daily_prices import DailyPrice

# Entities with no known market cap sort after everything that has one.
_UNKNOWN_CAP = float("inf")


async def latest_market_caps(session: AsyncSession) -> Dict[str, float]:
    """entity_id -> most recently ingested market cap (from daily_prices)."""
    rows = await session.exec(
        select(DailyPrice.entity_id, func.max(DailyPrice.market_cap))
        .where(DailyPrice.entity_id.isnot(None))  # type: ignore[union-attr]
        .where(DailyPrice.market_cap.isnot(None))  # type: ignore[union-attr]
        .group_by(DailyPrice.entity_id)
    )
    return {entity_id: cap for entity_id, cap in rows.all() if cap}


def order_smallest_first(
    entities: Sequence,
    caps: Dict[str, float],
    priority_ids: Iterable[str] = (),
) -> list:
    """Sort: dated-catalyst names first, then by market cap ascending.

    `priority_ids` keeps the calendar-inversion contract (RESTRUCTURE.md §3.1):
    anything with a dated upcoming catalyst outranks even the smallest cap.
    """
    priority = set(priority_ids)
    return sorted(
        entities,
        key=lambda e: (
            e.id not in priority,                 # False (priority) sorts first
            caps.get(e.id, _UNKNOWN_CAP),         # then smallest cap first
        ),
    )
