"""
Dashboard Router — CEO-friendly overview of engine status
"""
from fastapi import APIRouter, Depends
from sqlmodel import select, text
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import get_session
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal
from datetime import datetime, timedelta

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard")
async def get_dashboard(session: AsyncSession = Depends(get_session)):
    """CEO dashboard — plain English summary of what the engine found."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # Entities
    entities = (await session.exec(select(Entity).limit(10000))).all()
    private_count = len([e for e in entities if e.entity_type == "private"])
    public_count = len([e for e in entities if e.entity_type == "public"])

    # Signals
    all_signals = (await session.exec(select(Signal).limit(10000))).all()
    recent = [s for s in all_signals if s.created_at and s.created_at > week_ago]

    by_type = {}
    for s in all_signals:
        by_type[s.signal_type] = by_type.get(s.signal_type, 0) + 1

    by_source = {}
    for s in all_signals:
        by_source[s.source] = by_source.get(s.source, 0) + 1

    # Top entities by signal count
    entity_counts = {}
    for s in all_signals:
        if s.entity_id != "UNRESOLVED":
            entity_counts[s.entity_id] = entity_counts.get(s.entity_id, 0) + 1

    top_ids = sorted(entity_counts, key=entity_counts.get, reverse=True)[:10]
    entity_map = {e.id: e for e in entities}
    top_companies = []
    for eid in top_ids:
        e = entity_map.get(eid)
        if e:
            top_companies.append({
                "name": e.name, "type": e.entity_type,
                "stage": e.stage, "signals": entity_counts[eid],
            })

    # Themes
    try:
        theme_count = (await session.exec(text("SELECT COUNT(*) FROM themes"))).one()[0]
    except Exception:
        theme_count = 0

    return {
        "engine": "Alpha0Engine",
        "status": "running",
        "updated": now.isoformat(),
        "summary": {
            "companies_tracked": len(entities),
            "private": private_count,
            "public": public_count,
            "total_signals": len(all_signals),
            "signals_this_week": len(recent),
            "themes_detected": theme_count,
        },
        "signals_by_type": by_type,
        "signals_by_source": by_source,
        "top_companies": top_companies,
    }
