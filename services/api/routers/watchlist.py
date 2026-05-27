from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from shared.schemas.watchlist import (
    UserWatchlist,
    UserWatchlistCreate,
    UserWatchlistRead,
    UserWatchlistUpdate,
    WATCHLIST_PRIORITIES,
)

router = APIRouter(tags=["Watchlist"])


@router.post("/watchlist", response_model=UserWatchlistRead, status_code=201)
async def add_watchlist_item(
    item_in: UserWatchlistCreate,
    session: AsyncSession = Depends(get_session),
):
    ticker = item_in.ticker.upper().strip()
    if item_in.priority not in WATCHLIST_PRIORITIES:
        raise HTTPException(400, f"priority must be one of {WATCHLIST_PRIORITIES}")

    existing = await session.exec(select(UserWatchlist).where(UserWatchlist.ticker == ticker))
    found = existing.first()
    if found:
        found.hearted = True
        found.updated_at = datetime.now(timezone.utc)
        if item_in.notes is not None:
            found.notes = item_in.notes
        found.priority = item_in.priority
        found.catalyst_date = item_in.catalyst_date
        found.entity_id = item_in.entity_id
        session.add(found)
        await session.commit()
        await session.refresh(found)
        return found

    item = UserWatchlist.model_validate(item_in)
    item.ticker = ticker
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/watchlist", response_model=List[UserWatchlistRead])
async def list_watchlist_items(
    priority: Optional[str] = Query(None),
    hearted: Optional[bool] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
):
    query = select(UserWatchlist)
    if priority:
        if priority not in WATCHLIST_PRIORITIES:
            raise HTTPException(400, f"priority must be one of {WATCHLIST_PRIORITIES}")
        query = query.where(UserWatchlist.priority == priority)
    if hearted is not None:
        query = query.where(UserWatchlist.hearted == hearted)

    result = await session.exec(
        query.order_by(UserWatchlist.updated_at.desc()).offset(offset).limit(limit)
    )
    return result.all()


@router.patch("/watchlist/{item_id}", response_model=UserWatchlistRead)
async def update_watchlist_item(
    item_id: str,
    item_update: UserWatchlistUpdate,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(UserWatchlist, item_id)
    if not item:
        raise HTTPException(404, "Watchlist item not found")

    data = item_update.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"] not in WATCHLIST_PRIORITIES:
        raise HTTPException(400, f"priority must be one of {WATCHLIST_PRIORITIES}")

    for key, value in data.items():
        setattr(item, key, value)
    item.updated_at = datetime.now(timezone.utc)

    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/watchlist/{item_id}", status_code=204)
async def delete_watchlist_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(UserWatchlist, item_id)
    if not item:
        raise HTTPException(404, "Watchlist item not found")
    await session.delete(item)
    await session.commit()
    return None
