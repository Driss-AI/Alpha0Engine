from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, col, func
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from shared.schemas.brain_opportunity import BrainOpportunity, BrainOpportunityRead
from shared.schemas.brain_narrative import BrainNarrative, BrainNarrativeRead

router = APIRouter(tags=["Brain"])


@router.get("/brain/picks", response_model=List[BrainOpportunityRead])
async def get_brain_picks(
    days: int = Query(7, ge=1, le=90, description="Look back N days"),
    conviction: Optional[str] = Query(None, description="Filter: HIGH, MEDIUM, LOW"),
    status: str = Query("active", description="Filter: active, expired, hit, miss"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Daily picks — the Brain's asymmetric opportunity feed."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    query = select(BrainOpportunity).where(
        BrainOpportunity.generated_at >= cutoff,
        BrainOpportunity.status == status,
    )
    if conviction:
        query = query.where(BrainOpportunity.conviction == conviction.upper())

    query = query.order_by(col(BrainOpportunity.confidence_score).desc()).limit(limit)
    result = await session.exec(query)
    return result.all()


@router.get("/brain/picks/{pick_id}", response_model=BrainOpportunityRead)
async def get_brain_pick(
    pick_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Single opportunity with full thesis, scenarios, and citations."""
    result = await session.exec(
        select(BrainOpportunity).where(BrainOpportunity.id == pick_id)
    )
    opp = result.first()
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return opp


@router.get("/brain/{ticker}/narrative", response_model=BrainNarrativeRead)
async def get_brain_narrative(
    ticker: str,
    session: AsyncSession = Depends(get_session),
):
    """Latest AI narrative for a ticker."""
    result = await session.exec(
        select(BrainNarrative)
        .where(BrainNarrative.ticker == ticker.upper())
        .order_by(col(BrainNarrative.version).desc())
        .limit(1)
    )
    narrative = result.first()
    if not narrative:
        raise HTTPException(404, f"No brain narrative for {ticker.upper()}")
    return narrative


@router.get("/brain/{ticker}/history", response_model=List[BrainOpportunityRead])
async def get_brain_ticker_history(
    ticker: str,
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
):
    """All past Brain picks for a ticker (track conviction changes over time)."""
    result = await session.exec(
        select(BrainOpportunity)
        .where(BrainOpportunity.ticker == ticker.upper())
        .order_by(col(BrainOpportunity.generated_at).desc())
        .limit(limit)
    )
    return result.all()


@router.get("/brain/stats")
async def get_brain_stats(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Brain pipeline statistics."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    total_result = await session.exec(
        select(func.count(BrainOpportunity.id)).where(
            BrainOpportunity.generated_at >= cutoff
        )
    )
    total = total_result.one()

    by_conviction_result = await session.exec(
        select(BrainOpportunity.conviction, func.count(BrainOpportunity.id))
        .where(BrainOpportunity.generated_at >= cutoff)
        .group_by(BrainOpportunity.conviction)
    )
    by_conviction = {row[0]: row[1] for row in by_conviction_result.all()}

    by_status_result = await session.exec(
        select(BrainOpportunity.status, func.count(BrainOpportunity.id))
        .where(BrainOpportunity.generated_at >= cutoff)
        .group_by(BrainOpportunity.status)
    )
    by_status = {row[0]: row[1] for row in by_status_result.all()}

    avg_confidence_result = await session.exec(
        select(func.avg(BrainOpportunity.confidence_score)).where(
            BrainOpportunity.generated_at >= cutoff
        )
    )
    avg_confidence = avg_confidence_result.one()

    narrative_count_result = await session.exec(
        select(func.count(BrainNarrative.id)).where(
            BrainNarrative.generated_at >= cutoff
        )
    )
    narrative_count = narrative_count_result.one()

    return {
        "period_days": days,
        "total_opportunities": total,
        "by_conviction": by_conviction,
        "by_status": by_status,
        "avg_confidence_score": round(avg_confidence, 3) if avg_confidence else 0,
        "total_narratives": narrative_count,
        "generated_at": datetime.now(timezone.utc),
    }
