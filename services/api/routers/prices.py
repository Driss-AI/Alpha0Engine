"""
Prices Router — Market data API endpoints
Latest prices, penny stock filtering, price-enhanced screener data.
"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.daily_prices import DailyPrice
from shared.schemas.entities import Entity
from shared.clients.postgres import get_session

router = APIRouter(tags=["Prices"])


async def _get_latest_date(session: AsyncSession) -> Optional[date]:
    """Get the most recent trading date in the database."""
    result = await session.exec(
        select(DailyPrice.trade_date)
        .order_by(col(DailyPrice.trade_date).desc())
        .limit(1)
    )
    row = result.first()
    return row if row else None


@router.get("/prices")
async def list_latest_prices(
    max_price: Optional[float] = Query(None, description="Max stock price"),
    max_mcap: Optional[float] = Query(None, description="Max market cap"),
    penny_only: bool = Query(False, description="Only stocks under $5"),
    micro_only: bool = Query(False, description="Only stocks under $50 with mcap < $500M"),
    min_volume: Optional[float] = Query(None, description="Min avg daily volume"),
    limit: int = Query(50, le=500),
    session: AsyncSession = Depends(get_session),
):
    """Latest prices with filtering for penny/micro-cap discovery."""
    latest_date = await _get_latest_date(session)
    if not latest_date:
        return []

    query = select(DailyPrice).where(DailyPrice.trade_date == latest_date)

    if penny_only:
        query = query.where(DailyPrice.is_penny == True)
    if micro_only:
        query = query.where(DailyPrice.is_micro == True)
    if max_price is not None:
        query = query.where(DailyPrice.close <= max_price)
    if max_mcap is not None:
        query = query.where(DailyPrice.market_cap <= max_mcap)
    if min_volume is not None:
        query = query.where(DailyPrice.avg_volume_30d >= min_volume)

    query = query.order_by(col(DailyPrice.volume).desc()).limit(limit)
    rows = (await session.exec(query)).all()

    # Enrich with entity names
    entity_ids = [r.entity_id for r in rows if r.entity_id]
    entities = {}
    if entity_ids:
        ents = (await session.exec(
            select(Entity).where(col(Entity.id).in_(entity_ids))
        )).all()
        entities = {e.id: e for e in ents}

    return [
        {
            "ticker": r.ticker,
            "company_name": entities.get(r.entity_id, Entity(name="")).name if r.entity_id else None,
            "close": r.close,
            "volume": r.volume,
            "market_cap": r.market_cap,
            "change_pct": r.change_pct,
            "change_5d_pct": r.change_5d_pct,
            "change_20d_pct": r.change_20d_pct,
            "avg_volume_30d": r.avg_volume_30d,
            "is_penny": r.is_penny,
            "is_micro": r.is_micro,
            "trade_date": r.trade_date.isoformat() if r.trade_date else None,
        }
        for r in rows
    ]


@router.get("/prices/{ticker}")
async def get_ticker_prices(
    ticker: str,
    days: int = Query(30, le=365, description="Number of trading days"),
    session: AsyncSession = Depends(get_session),
):
    """Price history for a specific ticker."""
    result = await session.exec(
        select(DailyPrice)
        .where(DailyPrice.ticker == ticker.upper())
        .order_by(col(DailyPrice.trade_date).desc())
        .limit(days)
    )
    rows = result.all()

    if not rows:
        raise HTTPException(404, f"No price data for {ticker.upper()}")

    latest = rows[0]
    return {
        "ticker": ticker.upper(),
        "latest": {
            "close": latest.close,
            "volume": latest.volume,
            "market_cap": latest.market_cap,
            "change_pct": latest.change_pct,
            "change_5d_pct": latest.change_5d_pct,
            "change_20d_pct": latest.change_20d_pct,
            "avg_volume_30d": latest.avg_volume_30d,
            "is_penny": latest.is_penny,
            "is_micro": latest.is_micro,
            "trade_date": latest.trade_date.isoformat() if latest.trade_date else None,
        },
        "history": [
            {
                "date": r.trade_date.isoformat() if r.trade_date else None,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "change_pct": r.change_pct,
            }
            for r in reversed(rows)  # oldest first
        ],
    }


@router.get("/prices-summary")
async def prices_summary(session: AsyncSession = Depends(get_session)):
    """Price data overview for the dashboard."""
    latest_date = await _get_latest_date(session)
    if not latest_date:
        return {
            "total_tickers": 0, "latest_date": None,
            "penny_count": 0, "micro_count": 0,
        }

    latest_prices = (await session.exec(
        select(DailyPrice).where(DailyPrice.trade_date == latest_date).limit(10000)
    )).all()

    total = len(latest_prices)
    penny = sum(1 for p in latest_prices if p.is_penny)
    micro = sum(1 for p in latest_prices if p.is_micro)
    with_mcap = [p for p in latest_prices if p.market_cap and p.market_cap > 0]

    # Biggest movers
    movers_up = sorted(
        [p for p in latest_prices if p.change_pct is not None],
        key=lambda p: p.change_pct, reverse=True
    )[:5]
    movers_down = sorted(
        [p for p in latest_prices if p.change_pct is not None],
        key=lambda p: p.change_pct
    )[:5]

    # Market cap distribution
    mcap_buckets = {"nano_lt50M": 0, "micro_50_300M": 0, "small_300M_2B": 0, "mid_gt2B": 0}
    for p in with_mcap:
        mc = p.market_cap / 1e6
        if mc < 50:
            mcap_buckets["nano_lt50M"] += 1
        elif mc < 300:
            mcap_buckets["micro_50_300M"] += 1
        elif mc < 2000:
            mcap_buckets["small_300M_2B"] += 1
        else:
            mcap_buckets["mid_gt2B"] += 1

    return {
        "total_tickers": total,
        "latest_date": latest_date.isoformat(),
        "penny_count": penny,
        "micro_count": micro,
        "mcap_distribution": mcap_buckets,
        "top_gainers": [
            {"ticker": p.ticker, "close": p.close, "change_pct": p.change_pct,
             "volume": p.volume, "market_cap": p.market_cap}
            for p in movers_up
        ],
        "top_losers": [
            {"ticker": p.ticker, "close": p.close, "change_pct": p.change_pct,
             "volume": p.volume, "market_cap": p.market_cap}
            for p in movers_down
        ],
    }
