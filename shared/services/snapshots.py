from datetime import date

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.score_snapshot import ScoreSnapshot
from shared.schemas.equity_screen import EquityScreen

SNAPSHOT_BATCH_SIZE = 200


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
