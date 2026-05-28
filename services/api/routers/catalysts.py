from typing import List, Optional
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from middleware.auth import require_admin_key
from shared.schemas.catalyst_event import (
    CatalystEvent,
    CatalystEventCreate,
    CatalystEventRead,
    CatalystEventUpdate,
    CATALYST_TYPES,
    CATALYST_STATUSES,
)

router = APIRouter(tags=["Catalysts"])


def _parse_range(range_value: str) -> int:
    if not range_value.endswith("d"):
        raise HTTPException(400, "range must use day format, for example 30d")
    try:
        days = int(range_value[:-1])
    except ValueError:
        raise HTTPException(400, "range must use day format, for example 30d")
    if days < 1 or days > 365:
        raise HTTPException(400, "range must be between 1d and 365d")
    return days


@router.get("/catalysts/calendar", response_model=List[CatalystEventRead])
async def get_catalyst_calendar(
    range: str = Query("30d"),
    ticker: Optional[str] = Query(None),
    catalyst_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    days = _parse_range(range)
    start = date.today()
    end = start + timedelta(days=days)

    query = (
        select(CatalystEvent)
        .where(CatalystEvent.expected_date >= start)
        .where(CatalystEvent.expected_date <= end)
    )

    if ticker:
        query = query.where(CatalystEvent.ticker == ticker.upper())
    if catalyst_type:
        query = query.where(CatalystEvent.catalyst_type == catalyst_type)

    result = await session.exec(query.order_by(CatalystEvent.expected_date.asc()))
    return result.all()


@router.get("/catalysts", response_model=List[CatalystEventRead])
async def list_catalysts(
    ticker: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    query = select(CatalystEvent)

    if ticker:
        query = query.where(CatalystEvent.ticker == ticker.upper())
    if status:
        if status not in CATALYST_STATUSES:
            raise HTTPException(400, f"status must be one of {CATALYST_STATUSES}")
        query = query.where(CatalystEvent.status == status)

    result = await session.exec(
        query.order_by(CatalystEvent.expected_date.asc()).offset(offset).limit(limit)
    )
    return result.all()


@router.post("/catalysts/pin", response_model=CatalystEventRead, status_code=201)
async def pin_catalyst(
    event_in: CatalystEventCreate,
    session: AsyncSession = Depends(get_session),
    _key: str = Depends(require_admin_key),
):
    if event_in.catalyst_type not in CATALYST_TYPES:
        raise HTTPException(400, f"catalyst_type must be one of {CATALYST_TYPES}")
    if event_in.status not in CATALYST_STATUSES:
        raise HTTPException(400, f"status must be one of {CATALYST_STATUSES}")

    event = CatalystEvent.model_validate(event_in)
    event.ticker = event.ticker.upper().strip()
    event.user_pinned = True

    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


@router.patch("/catalysts/{event_id}", response_model=CatalystEventRead)
async def update_catalyst(
    event_id: str,
    event_update: CatalystEventUpdate,
    session: AsyncSession = Depends(get_session),
    _key: str = Depends(require_admin_key),
):
    event = await session.get(CatalystEvent, event_id)
    if not event:
        raise HTTPException(404, "Catalyst event not found")

    data = event_update.model_dump(exclude_unset=True)

    if "catalyst_type" in data and data["catalyst_type"] not in CATALYST_TYPES:
        raise HTTPException(400, f"catalyst_type must be one of {CATALYST_TYPES}")
    if "status" in data and data["status"] not in CATALYST_STATUSES:
        raise HTTPException(400, f"status must be one of {CATALYST_STATUSES}")

    for key, value in data.items():
        setattr(event, key, value)

    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event
