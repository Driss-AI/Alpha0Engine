from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.entities import Entity, EntityCreate, EntityRead, EntityUpdate
from shared.clients.postgres import get_session

router = APIRouter(tags=["Entities"])


@router.get("/entities", response_model=List[EntityRead])
async def list_entities(
    entity_type: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    query = select(Entity)
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    if sector:
        query = query.where(Entity.sector == sector)
    if stage:
        query = query.where(Entity.stage == stage)
    result = await session.exec(query.offset(offset).limit(limit))
    return result.all()


@router.get("/entities/{entity_id}", response_model=EntityRead)
async def get_entity(entity_id: str, session: AsyncSession = Depends(get_session)):
    entity = await session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, f"Entity {entity_id} not found")
    return entity


@router.post("/entities", response_model=EntityRead, status_code=201)
async def create_entity(entity_in: EntityCreate, session: AsyncSession = Depends(get_session)):
    entity = Entity.from_orm(entity_in)
    session.add(entity)
    await session.commit()
    await session.refresh(entity)
    return entity


@router.patch("/entities/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: str,
    updates: EntityUpdate,
    session: AsyncSession = Depends(get_session),
):
    entity = await session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, f"Entity {entity_id} not found")
    for field, value in updates.dict(exclude_unset=True).items():
        setattr(entity, field, value)
    entity.updated_at = datetime.utcnow()
    session.add(entity)
    await session.commit()
    await session.refresh(entity)
    return entity
