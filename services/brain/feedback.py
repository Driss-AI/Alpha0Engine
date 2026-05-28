"""
Feedback Loop
=============
Compares Brain picks against current prices to track performance.

Rules:
  - HIT:  price reached ≥50% of bull target move, OR return ≥ 100%
  - MISS: expired and price below pick price or barely moved (<10%)
  - EXPIRED → HIT/MISS: auto-resolved when expires_at passes

Runs daily after the brain analysis pipeline.
"""
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.brain_opportunity import BrainOpportunity
from shared.schemas.daily_prices import DailyPrice

logger = logging.getLogger("brain.feedback")

HIT_RETURN_PCT = 100.0
HIT_TARGET_FRACTION = 0.50
MISS_CEILING_PCT = 10.0
STOP_LOSS_PCT = -50.0


async def _get_latest_price(session: AsyncSession, ticker: str) -> Optional[float]:
    result = await session.exec(
        select(DailyPrice.close)
        .where(DailyPrice.ticker == ticker, DailyPrice.close.isnot(None))
        .order_by(DailyPrice.trade_date.desc())
        .limit(1)
    )
    return result.first()


def _evaluate_pick(
    opp: BrainOpportunity,
    current_price: float,
    now: datetime,
) -> tuple:
    """Returns (new_status, return_pct, feedback_notes) or (None, ...) if no change."""
    pick_price = opp.price_at_pick
    if not pick_price or pick_price <= 0:
        return None, None, None

    return_pct = ((current_price - pick_price) / pick_price) * 100.0
    is_expired = opp.expires_at and now >= opp.expires_at

    if return_pct >= HIT_RETURN_PCT:
        return "hit", return_pct, f"Return {return_pct:+.1f}% exceeded {HIT_RETURN_PCT}% threshold"

    if opp.price_target_bull and pick_price > 0:
        target_move = opp.price_target_bull - pick_price
        if target_move > 0:
            actual_move = current_price - pick_price
            fraction = actual_move / target_move
            if fraction >= HIT_TARGET_FRACTION:
                return "hit", return_pct, f"Reached {fraction:.0%} of bull target (${opp.price_target_bull})"

    if return_pct <= STOP_LOSS_PCT:
        return "miss", return_pct, f"Stop-loss triggered at {return_pct:+.1f}%"

    if is_expired:
        if return_pct > MISS_CEILING_PCT:
            return "hit", return_pct, f"Expired with {return_pct:+.1f}% gain"
        else:
            return "miss", return_pct, f"Expired with {return_pct:+.1f}% return"

    return None, return_pct, None


async def run_feedback(session: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """Evaluate all active picks and update their status."""
    await create_db_and_tables()

    own_session = session is None
    if own_session:
        session = AsyncSessionLocal()

    stats = {
        "active_checked": 0,
        "prices_updated": 0,
        "newly_hit": 0,
        "newly_missed": 0,
        "no_price_data": 0,
        "unchanged": 0,
        "details": [],
    }

    try:
        result = await session.exec(
            select(BrainOpportunity).where(BrainOpportunity.status == "active")
        )
        active_picks = result.all()
        stats["active_checked"] = len(active_picks)

        if not active_picks:
            logger.info("No active picks to evaluate")
            return stats

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for opp in active_picks:
            ticker = opp.ticker or ""
            if not ticker:
                continue

            current_price = await _get_latest_price(session, ticker)
            if current_price is None:
                stats["no_price_data"] += 1
                continue

            opp.price_latest = current_price

            new_status, return_pct, notes = _evaluate_pick(opp, current_price, now)

            if return_pct is not None:
                opp.return_pct = round(return_pct, 2)

            if new_status:
                opp.status = new_status
                opp.resolved_at = now
                opp.feedback_notes = notes
                opp.updated_at = now

                if new_status == "hit":
                    stats["newly_hit"] += 1
                else:
                    stats["newly_missed"] += 1

                stats["details"].append({
                    "ticker": ticker,
                    "status": new_status,
                    "return_pct": round(return_pct, 2) if return_pct else 0,
                    "notes": notes,
                })
                logger.info(f"  {ticker}: {new_status.upper()} — {notes}")
            else:
                opp.updated_at = now
                stats["unchanged"] += 1

            stats["prices_updated"] += 1

        if own_session:
            await session.commit()
        else:
            await session.flush()

    finally:
        if own_session:
            await session.close()

    logger.info("=" * 60)
    logger.info("FEEDBACK LOOP COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Active checked:  {stats['active_checked']}")
    logger.info(f"  Prices updated:  {stats['prices_updated']}")
    logger.info(f"  Newly hit:       {stats['newly_hit']}")
    logger.info(f"  Newly missed:    {stats['newly_missed']}")
    logger.info(f"  Unchanged:       {stats['unchanged']}")
    logger.info(f"  No price data:   {stats['no_price_data']}")

    return stats
