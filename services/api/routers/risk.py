"""
Risk Router — Module 4 API endpoints
Risk assessments, hype flags, and illiquidity alerts.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.risk import RiskAssessment, RiskAssessmentRead
from shared.schemas.entities import Entity
from shared.clients.postgres import get_session

router = APIRouter(tags=["Risk Filtering"])


@router.get("/risk", response_model=List[RiskAssessmentRead])
async def list_risk_assessments(
    tier: Optional[str] = Query(None, description="Filter: GREEN/YELLOW/ORANGE/RED"),
    flagged_only: bool = Query(False, description="Only show flagged entities"),
    min_risk: float = Query(0.0, description="Minimum risk score"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List all risk assessments, sorted by risk score."""
    query = select(RiskAssessment).where(RiskAssessment.risk_score >= min_risk)
    if tier:
        query = query.where(RiskAssessment.risk_tier == tier.upper())
    if flagged_only:
        query = query.where(
            (RiskAssessment.hype_flag == True) | (RiskAssessment.illiquidity_flag == True)
        )
    query = query.order_by(col(RiskAssessment.risk_score).desc()).limit(limit)
    return (await session.exec(query)).all()


@router.get("/risk/{entity_id}", response_model=RiskAssessmentRead)
async def get_entity_risk(entity_id: str, session: AsyncSession = Depends(get_session)):
    """Get detailed risk assessment for a specific entity."""
    result = await session.exec(
        select(RiskAssessment).where(RiskAssessment.entity_id == entity_id)
    )
    risk = result.first()
    if not risk:
        raise HTTPException(status_code=404, detail="No risk assessment for this entity")
    return risk


@router.get("/risk-alerts")
async def risk_alerts(
    min_risk: float = Query(0.5, description="Minimum risk score for alerts"),
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Active risk alerts — companies exceeding risk thresholds."""
    query = select(RiskAssessment, Entity).join(
        Entity, RiskAssessment.entity_id == Entity.id
    ).where(
        RiskAssessment.risk_score >= min_risk
    ).order_by(col(RiskAssessment.risk_score).desc()).limit(limit)

    rows = (await session.exec(query)).all()
    return [
        {
            "entity_id": risk.entity_id,
            "company_name": entity.name,
            "entity_type": entity.entity_type,
            "sector": entity.sector,
            "risk_tier": risk.risk_tier,
            "risk_score": risk.risk_score,
            "hype_flag": risk.hype_flag,
            "hype_gap": risk.hype_gap,
            "illiquidity_flag": risk.illiquidity_flag,
            "illiquidity_score": risk.illiquidity_score,
            "runway_risk": risk.runway_risk,
            "risk_flags": risk.risk_flags,
            "risk_notes": risk.risk_notes,
            "assessed_at": risk.assessed_at.isoformat() if risk.assessed_at else None,
        }
        for risk, entity in rows
    ]


@router.get("/risk-summary")
async def risk_summary(session: AsyncSession = Depends(get_session)):
    """Risk overview for the CEO dashboard."""
    all_risks = (await session.exec(select(RiskAssessment).limit(5000))).all()
    total = len(all_risks)
    tier_counts = {"GREEN": 0, "YELLOW": 0, "ORANGE": 0, "RED": 0}
    hype_flagged = 0
    illiquidity_flagged = 0
    avg_risk = 0.0

    for r in all_risks:
        tier_counts[r.risk_tier] = tier_counts.get(r.risk_tier, 0) + 1
        if r.hype_flag:
            hype_flagged += 1
        if r.illiquidity_flag:
            illiquidity_flagged += 1
        avg_risk += r.risk_score

    if total > 0:
        avg_risk = round(avg_risk / total, 4)

    # Top 5 riskiest
    top_risky = sorted(all_risks, key=lambda x: x.risk_score, reverse=True)[:5]
    top_ids = [r.entity_id for r in top_risky]
    entities = (await session.exec(select(Entity).where(col(Entity.id).in_(top_ids)))).all()
    name_map = {e.id: e.name for e in entities}

    return {
        "total_assessed": total,
        "tier_breakdown": tier_counts,
        "avg_risk_score": avg_risk,
        "hype_flagged": hype_flagged,
        "illiquidity_flagged": illiquidity_flagged,
        "riskiest_companies": [
            {"name": name_map.get(r.entity_id, "Unknown"), "tier": r.risk_tier,
             "score": r.risk_score, "flags": r.risk_flags}
            for r in top_risky
        ],
    }
