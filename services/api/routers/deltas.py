from typing import Dict, Any, List
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from shared.schemas.score_snapshot import ScoreSnapshot
from shared.schemas.equity_screen import EquityScreen

SNAPSHOT_BATCH_SIZE = 200

router = APIRouter(tags=["Deltas"])


@router.post("/1000x/snapshots/write")
async def write_daily_snapshots_endpoint(
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    count = await write_daily_snapshots(session)
    return {"status": "ok", "snapshots_written": count}


async def write_daily_snapshots(session: AsyncSession) -> int:
    today = date.today()
    total_count = 0
    offset = 0

    while True:
        batch_result = await session.exec(
            select(EquityScreen)
            .offset(offset)
            .limit(SNAPSHOT_BATCH_SIZE)
        )
        batch = batch_result.all()
        if not batch:
            break

        for screen in batch:
            if not screen.ticker:
                continue

            existing = await session.exec(
                select(ScoreSnapshot)
                .where(ScoreSnapshot.ticker == screen.ticker.upper())
                .where(ScoreSnapshot.snapshot_date == today)
            )
            snapshot = existing.first()

            if not snapshot:
                snapshot = ScoreSnapshot(
                    ticker=screen.ticker.upper(),
                    entity_id=screen.entity_id,
                    composite_score=screen.composite_score,
                    catalyst_score=screen.catalyst_score,
                    earnings_score=screen.earnings_score,
                    demand_score=screen.demand_score,
                    float_score=screen.float_score,
                    smart_money_score=screen.smart_money_score,
                    active_lenses=screen.active_lenses,
                    conviction_tier=screen.conviction_tier,
                    snapshot_date=today,
                )
            else:
                snapshot.composite_score = screen.composite_score
                snapshot.catalyst_score = screen.catalyst_score
                snapshot.earnings_score = screen.earnings_score
                snapshot.demand_score = screen.demand_score
                snapshot.float_score = screen.float_score
                snapshot.smart_money_score = screen.smart_money_score
                snapshot.active_lenses = screen.active_lenses
                snapshot.conviction_tier = screen.conviction_tier

            session.add(snapshot)
            total_count += 1

        await session.commit()
        offset += SNAPSHOT_BATCH_SIZE

    return total_count


@router.get("/1000x/deltas")
async def get_deltas(
    days: int = Query(1, ge=1, le=90),
    limit: int = Query(50, le=500),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    today = date.today()
    prior_day = today - timedelta(days=days)

    snapshot_cols = select(
        ScoreSnapshot.ticker,
        ScoreSnapshot.composite_score,
        ScoreSnapshot.conviction_tier,
    )
    current_rows = await session.exec(snapshot_cols.where(ScoreSnapshot.snapshot_date == today))
    prior_rows = await session.exec(snapshot_cols.where(ScoreSnapshot.snapshot_date == prior_day))

    current = {row.ticker: row for row in current_rows.all()}
    prior = {row.ticker: row for row in prior_rows.all()}

    movers = []
    tier_changes = []
    new_entries = []
    disappeared = []

    for ticker, curr in current.items():
        old = prior.get(ticker)
        if not old:
            new_entries.append({"ticker": ticker, "score": curr.composite_score})
            continue

        delta = curr.composite_score - old.composite_score
        if delta != 0:
            movers.append(
                {
                    "ticker": ticker,
                    "old_score": old.composite_score,
                    "new_score": curr.composite_score,
                    "delta": delta,
                }
            )

        if curr.conviction_tier != old.conviction_tier:
            tier_changes.append(
                {
                    "ticker": ticker,
                    "old_tier": old.conviction_tier,
                    "new_tier": curr.conviction_tier,
                }
            )

    for ticker, old in prior.items():
        if ticker not in current:
            disappeared.append({"ticker": ticker, "old_score": old.composite_score})

    movers.sort(key=lambda item: abs(item["delta"]), reverse=True)

    return {
        "date": today,
        "compare_to": prior_day,
        "movers": movers[:limit],
        "tier_changes": tier_changes[:limit],
        "new_entries": new_entries[:limit],
        "disappeared": disappeared[:limit],
    }


@router.get("/1000x/movers")
async def get_movers(
    direction: str = Query("up", pattern="^(up|down)$"),
    days: int = Query(1, ge=1, le=90),
    limit: int = Query(10, le=100),
    session: AsyncSession = Depends(get_session),
) -> List[Dict[str, Any]]:
    deltas = await get_deltas(days=days, limit=500, session=session)
    movers = deltas["movers"]

    if direction == "up":
        movers = [item for item in movers if item["delta"] > 0]
        movers.sort(key=lambda item: item["delta"], reverse=True)
    else:
        movers = [item for item in movers if item["delta"] < 0]
        movers.sort(key=lambda item: item["delta"])

    return movers[:limit]


@router.get("/1000x/new-entries")
async def get_new_entries(
    days: int = Query(1, ge=1, le=90),
    limit: int = Query(50, le=500),
    session: AsyncSession = Depends(get_session),
):
    deltas = await get_deltas(days=days, limit=limit, session=session)
    return deltas["new_entries"]
