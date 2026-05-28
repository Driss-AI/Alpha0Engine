from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.signals import Signal, SignalCreate, SignalRead, SIGNAL_TYPES
from shared.clients.postgres import get_session
from middleware.auth import require_admin_key

router = APIRouter(tags=["Signals"])


@router.get("/signals", response_model=List[SignalRead])
async def list_signals(
    entity_id: Optional[str] = Query(None),
    signal_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    query = select(Signal)
    if entity_id:
        query = query.where(Signal.entity_id == entity_id)
    if signal_type:
        if signal_type not in SIGNAL_TYPES:
            raise HTTPException(400, f"Unknown signal_type: {signal_type}")
        query = query.where(Signal.signal_type == signal_type)
    if source:
        query = query.where(Signal.source == source)
    if from_date:
        query = query.where(Signal.signal_date >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query = query.where(Signal.signal_date <= datetime.combine(to_date, datetime.max.time()))
    result = await session.exec(query.order_by(Signal.signal_date.desc()).offset(offset).limit(limit))
    return result.all()


@router.post("/signals", response_model=SignalRead, status_code=201)
async def create_signal(signal_in: SignalCreate, session: AsyncSession = Depends(get_session), _key: str = Depends(require_admin_key)):
    signal = Signal.from_orm(signal_in)
    session.add(signal)
    await session.commit()
    await session.refresh(signal)
    return signal


@router.get("/entities/{entity_id}/signals", response_model=List[SignalRead])
async def get_entity_signals(
    entity_id: str,
    signal_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    session: AsyncSession = Depends(get_session),
):
    query = select(Signal).where(Signal.entity_id == entity_id)
    if signal_type:
        query = query.where(Signal.signal_type == signal_type)
    result = await session.exec(query.order_by(Signal.signal_date.desc()).limit(limit))
    return result.all()
