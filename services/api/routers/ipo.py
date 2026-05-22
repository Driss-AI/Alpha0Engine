"""
IPO Proximity Router — pre-IPO candidate rankings
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import JSON

from shared.schemas.signals import Signal, SignalRead
from shared.clients.postgres import get_session

router = APIRouter(tags=["IPO Proximity"])


@router.get("/ipo-candidates", response_model=List[SignalRead])
async def list_ipo_candidates(
    min_score: float = Query(0.3, description="Minimum IPO proximity score"),
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List companies ranked by IPO proximity score."""
    result = await session.exec(
        select(Signal)
        .where(Signal.source == "nlp_engine")
        .where(Signal.value >= min_score)
        .order_by(Signal.value.desc())
        .limit(limit)
    )
    return result.all()
