"""
Fundamentals Router — Module 3 API endpoints
Screening scores, moat analysis, and company fundamentals.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.fundamentals import FundamentalScore, FundamentalScoreRead
from shared.schemas.entities import Entity
from shared.clients.postgres import get_session

router = APIRouter(tags=["Fundamental Screening"])


@router.get("/fundamentals", response_model=List[FundamentalScoreRead])
async def list_fundamentals(
    tier: Optional[str] = Query(None, description="Filter by tier: S/A/B/C/D"),
    entity_type: Optional[str] = Query(None, description="Filter: public or private"),
    min_score: float = Query(0.0, description="Minimum fundamental score"),
    sort_by: str = Query("fundamental_score", description="Sort field"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List all screened companies with their fundamental scores."""
    query = select(FundamentalScore).where(
        FundamentalScore.fundamental_score >= min_score
    )

    if tier:
        query = query.where(FundamentalScore.screening_tier == tier.upper())

    if sort_by == "moat_score":
        query = query.order_by(col(FundamentalScore.moat_score).desc())
    elif sort_by == "updated_at":
        query = query.order_by(col(FundamentalScore.updated_at).desc())
    else:
        query = query.order_by(col(FundamentalScore.fundamental_score).desc())

    query = query.limit(limit)
    result = await session.exec(query)
    scores = result.all()

    if entity_type:
        entity_ids = [s.entity_id for s in scores]
        entities = (await session.exec(
            select(Entity).where(col(Entity.id).in_(entity_ids))
        )).all()
        entity_map = {e.id: e for e in entities}
        scores = [s for s in scores if entity_map.get(s.entity_id, Entity(name="")).entity_type == entity_type]

    return scores


@router.get("/fundamentals/{entity_id}", response_model=FundamentalScoreRead)
async def get_entity_fundamentals(
    entity_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get detailed fundamental score for a specific entity."""
    result = await session.exec(
        select(FundamentalScore).where(FundamentalScore.entity_id == entity_id)
    )
    score = result.first()
    if not score:
        raise HTTPException(status_code=404, detail="No fundamental score found for this entity")
    return score


@router.get("/screener")
async def run_screener(
    min_moat: float = Query(0.0, description="Minimum moat score"),
    min_fundamental: float = Query(0.0, description="Minimum fundamental score"),
    tiers: Optional[str] = Query(None, description="Comma-separated tiers: S,A,B"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """
    Interactive screener — filter and rank companies.
    Joins entity info with fundamental scores.
    """
    query = select(FundamentalScore, Entity).join(
        Entity, FundamentalScore.entity_id == Entity.id
    ).where(
        FundamentalScore.moat_score >= min_moat,
        FundamentalScore.fundamental_score >= min_fundamental,
    )

    if tiers:
        tier_list = [t.strip().upper() for t in tiers.split(",")]
        query = query.where(col(FundamentalScore.screening_tier).in_(tier_list))

    if sector:
        query = query.where(Entity.sector == sector)

    query = query.order_by(col(FundamentalScore.fundamental_score).desc()).limit(limit)

    result = await session.exec(query)
    rows = result.all()

    return [
        {
            "entity_id": score.entity_id,
            "company_name": entity.name,
            "entity_type": entity.entity_type,
            "sector": entity.sector,
            "stage": entity.stage,
            "screening_tier": score.screening_tier,
            "fundamental_score": score.fundamental_score,
            "moat_score": score.moat_score,
            "patent_strength": score.patent_strength,
            "talent_density": score.talent_density,
            "github_momentum": score.github_momentum,
            "competitive_position": score.competitive_position,
            "gross_margin": score.gross_margin,
            "revenue_growth_yoy": score.revenue_growth_yoy,
            "cash_runway_months": score.cash_runway_months,
            "rule_of_40": score.rule_of_40,
            "estimated_runway_months": score.estimated_runway_months,
            "total_raised": score.total_raised,
            "screening_notes": score.screening_notes,
            "scored_at": score.scored_at.isoformat() if score.scored_at else None,
        }
        for score, entity in rows
    ]


@router.get("/screener/summary")
async def screener_summary(
    session: AsyncSession = Depends(get_session),
):
    """Screening summary — high-level stats for the CEO dashboard."""
    all_scores = (await session.exec(select(FundamentalScore).limit(5000))).all()

    tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    total_scored = len(all_scores)
    avg_moat = 0.0
    avg_fundamental = 0.0

    for s in all_scores:
        tier_counts[s.screening_tier] = tier_counts.get(s.screening_tier, 0) + 1
        avg_moat += s.moat_score
        avg_fundamental += s.fundamental_score

    if total_scored > 0:
        avg_moat = round(avg_moat / total_scored, 4)
        avg_fundamental = round(avg_fundamental / total_scored, 4)

    top_5 = sorted(all_scores, key=lambda x: x.fundamental_score, reverse=True)[:5]
    top_ids = [s.entity_id for s in top_5]
    entities = (await session.exec(
        select(Entity).where(col(Entity.id).in_(top_ids))
    )).all()
    name_map = {e.id: e.name for e in entities}

    return {
        "total_screened": total_scored,
        "tier_breakdown": tier_counts,
        "avg_moat_score": avg_moat,
        "avg_fundamental_score": avg_fundamental,
        "top_companies": [
            {
                "name": name_map.get(s.entity_id, "Unknown"),
                "tier": s.screening_tier,
                "score": s.fundamental_score,
                "moat": s.moat_score,
            }
            for s in top_5
        ],
    }
