#!/usr/bin/env python3
"""
Backtest Dataset Builder
========================
Pulls historical score snapshots, joins with daily prices to compute
actual returns at 30/90/180/365-day horizons, and writes results to
the score_validations table.

Usage:
    python scripts/backtest_dataset.py              # all historical snapshots
    python scripts/backtest_dataset.py --days 90    # only last 90 days
    python scripts/backtest_dataset.py --dry-run    # preview without writing

Requires DATABASE_URL pointing to the production Postgres instance.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.score_snapshot import ScoreSnapshot
from shared.schemas.daily_prices import DailyPrice
from shared.schemas.score_validation import ScoreValidation
from shared.logging import setup_logging, get_logger

setup_logging("backtest-dataset")
logger = get_logger("backtest-dataset")

HORIZONS = [30, 90, 180, 365]
BATCH_SIZE = 100
WIN_THRESHOLD = 0.10   # ≥10% return = win
LOSS_THRESHOLD = -0.10  # ≤-10% return = loss


def classify_outcome(return_pct: float) -> str:
    if return_pct >= WIN_THRESHOLD:
        return "win"
    elif return_pct <= LOSS_THRESHOLD:
        return "loss"
    return "flat"


async def get_price_on_date(
    session: AsyncSession, ticker: str, target_date: date, window_days: int = 5
) -> float | None:
    """Get closing price on or near a date (within ±window_days for non-trading days)."""
    result = await session.exec(
        select(DailyPrice)
        .where(DailyPrice.ticker == ticker.upper())
        .where(DailyPrice.trade_date >= target_date - timedelta(days=window_days))
        .where(DailyPrice.trade_date <= target_date + timedelta(days=window_days))
        .order_by(
            col(DailyPrice.trade_date).desc()
            if target_date >= date.today()
            else col(DailyPrice.trade_date).asc()
        )
        .limit(1)
    )
    row = result.first()
    return row.close if row and row.close else None


async def compute_max_drawdown_gain(
    session: AsyncSession, ticker: str, start_date: date, days: int, base_price: float
) -> tuple[float | None, float | None]:
    """Compute max drawdown and max gain within a window."""
    end_date = start_date + timedelta(days=days)
    result = await session.exec(
        select(DailyPrice)
        .where(DailyPrice.ticker == ticker.upper())
        .where(DailyPrice.trade_date > start_date)
        .where(DailyPrice.trade_date <= end_date)
    )
    prices = result.all()
    if not prices or base_price <= 0:
        return None, None

    max_gain = 0.0
    max_drawdown = 0.0
    for p in prices:
        if p.close and p.close > 0:
            ret = (p.close - base_price) / base_price
            max_gain = max(max_gain, ret)
            max_drawdown = min(max_drawdown, ret)

    return round(max_drawdown, 4), round(max_gain, 4)


async def build_validation_row(
    session: AsyncSession, snapshot: ScoreSnapshot
) -> ScoreValidation | None:
    """Build a ScoreValidation from a snapshot by looking up actual prices."""
    ticker = snapshot.ticker
    snap_date = snapshot.snapshot_date
    today = date.today()

    base_price = await get_price_on_date(session, ticker, snap_date)
    if not base_price or base_price <= 0:
        return None

    row = ScoreValidation(
        ticker=ticker,
        entity_id=snapshot.entity_id,
        snapshot_date=snap_date,
        lane_id=snapshot.lane_id,   # S10: carry lane through to the validation row
        composite_score=snapshot.composite_score,
        conviction_tier=snapshot.conviction_tier or "unscored",
        active_lenses=snapshot.active_lenses or 0,
        catalyst_score=snapshot.catalyst_score,
        earnings_score=snapshot.earnings_score,
        demand_score=snapshot.demand_score,
        float_score=snapshot.float_score,
        smart_money_score=snapshot.smart_money_score,
        price_at_snapshot=base_price,
    )

    for horizon in HORIZONS:
        target_date = snap_date + timedelta(days=horizon)
        if target_date > today:
            continue

        future_price = await get_price_on_date(session, ticker, target_date)
        if not future_price or future_price <= 0:
            continue

        ret = round((future_price - base_price) / base_price, 4)
        outcome = classify_outcome(ret)

        setattr(row, f"return_{horizon}d", ret)
        setattr(row, f"price_{horizon}d", future_price)
        setattr(row, f"outcome_{horizon}d", outcome)

        if horizon <= 90:
            dd, mg = await compute_max_drawdown_gain(
                session, ticker, snap_date, horizon, base_price
            )
            setattr(row, f"max_drawdown_{horizon}d", dd)
            setattr(row, f"max_gain_{horizon}d", mg)

    return row


async def run(days: int | None, dry_run: bool, lane: str | None = None):
    logger.info("Starting backtest dataset build",
                extra={"days": days, "lane": lane, "action": "backtest_build"})

    async with AsyncSessionLocal() as session:
        query = select(ScoreSnapshot).order_by(col(ScoreSnapshot.snapshot_date).asc())
        if days:
            cutoff = date.today() - timedelta(days=days)
            query = query.where(ScoreSnapshot.snapshot_date >= cutoff)
        if lane:
            query = query.where(ScoreSnapshot.lane_id == lane)

        snapshots = (await session.exec(query)).all()
        logger.info(f"Found {len(snapshots)} snapshots to process", extra={"records": len(snapshots)})

        if not snapshots:
            logger.info("No snapshots found — nothing to backtest")
            return

        created = 0
        updated = 0
        skipped = 0

        for i, snap in enumerate(snapshots):
            existing = (await session.exec(
                select(ScoreValidation)
                .where(ScoreValidation.ticker == snap.ticker)
                .where(ScoreValidation.snapshot_date == snap.snapshot_date)
            )).first()

            if existing and existing.return_365d is not None:
                skipped += 1
                continue

            row = await build_validation_row(session, snap)
            if not row:
                skipped += 1
                continue

            if dry_run:
                logger.info(
                    f"[DRY RUN] {snap.ticker} {snap.snapshot_date} "
                    f"tier={snap.conviction_tier} score={snap.composite_score:.3f} "
                    f"ret_30d={row.return_30d} ret_90d={row.return_90d}"
                )
                created += 1
                continue

            if existing:
                for field in ["return_30d", "return_90d", "return_180d", "return_365d",
                              "price_30d", "price_90d", "price_180d", "price_365d",
                              "max_drawdown_30d", "max_gain_30d", "max_drawdown_90d", "max_gain_90d",
                              "outcome_30d", "outcome_90d", "outcome_180d", "outcome_365d"]:
                    new_val = getattr(row, field)
                    if new_val is not None:
                        setattr(existing, field, new_val)
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(existing)
                updated += 1
            else:
                session.add(row)
                created += 1

            if (i + 1) % BATCH_SIZE == 0:
                if not dry_run:
                    await session.commit()
                logger.info(
                    f"Progress: {i + 1}/{len(snapshots)} "
                    f"(created={created}, updated={updated}, skipped={skipped})"
                )

        if not dry_run:
            await session.commit()

    logger.info(
        f"Backtest dataset complete: {created} created, {updated} updated, {skipped} skipped",
        extra={"action": "backtest_complete", "records": created + updated},
    )


def main():
    parser = argparse.ArgumentParser(description="Build backtest validation dataset")
    parser.add_argument("--days", type=int, default=None, help="Only process last N days of snapshots")
    parser.add_argument("--lane", default=None, help="Only process one lane (L1_AI_INFRA / L2_BIOTECH)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()
    asyncio.run(run(args.days, args.dry_run, args.lane))


if __name__ == "__main__":
    main()
