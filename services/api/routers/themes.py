"""
Themes Router — emerging megatrend detection results
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.themes import Theme, ThemeRead, ThemeEntity
from shared.clients.postgres import get_session

router = APIRouter(tags=["Themes"])


@router.get("/themes", response_model=List[ThemeRead])
async def list_themes(
    status: Optional[str] = Query(None, description="emerging|active|cooling"),
    min_velocity: float = Query(0.0),
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List detected megatrend themes, sorted by velocity."""
    query = select(Theme)
    if status:
        query = query.where(Theme.status == status)
    if min_velocity > 0:
        query = query.where(Theme.velocity_score >= min_velocity)
    query = query.order_by(Theme.velocity_score.desc()).limit(limit)
    result = await session.exec(query)
    return result.all()


@router.get("/themes/{theme_id}/entities")
async def get_theme_entities(
    theme_id: str,
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get all entities in a theme cluster."""
    result = await session.exec(
        select(ThemeEntity)
        .where(ThemeEntity.theme_id == theme_id)
        .order_by(ThemeEntity.similarity_score.desc())
        .limit(limit)
    )
    return result.all()
