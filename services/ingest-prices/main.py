"""
Price Ingestion Worker
=======================
The data backbone. Pulls daily OHLCV for all tracked tickers,
computes market cap, and propagates real prices into every scoring table.

Runs daily after market close. Also runs universe discovery weekly
to find new sub-$500M public companies from the SEC ticker list.

This single service makes every existing lens immediately accurate:
  - Real market cap → Lens 1 (inverse mcap), Lens 4 (float), Lens 5 (value ratios)
  - Real volume → Lens 4 (days-to-cover)
  - Real price → penny/micro-cap filtering
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.daily_prices import DailyPrice
from shared.schemas.fundamentals import FundamentalScore
from shared.schemas.equity_screen import EquityScreen

from price_fetcher import fetch_batch_prices, fetch_market_caps, fetch_universe_tickers_sec

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-prices")

PRICE_BATCH = 80       # tickers per yfinance batch
MCAP_BATCH = 20        # tickers per .info call batch (slower)
UNIVERSE_MAX = 5000    # max new entities to create per discovery run


# ═══════════════════════════════════════════════════════════
# 1. DAILY PRICE INGESTION
# ═══════════════════════════════════════════════════════════

async def get_all_tickers(session: AsyncSession) -> list:
    """Get all entities that have tickers."""
    result = await session.exec(
        select(Entity).where(
            Entity.ticker.isnot(None),  # type: ignore
            Entity.entity_type == "public",
        ).limit(10000)
    )
    return result.all()


async def store_prices(
    session: AsyncSession,
    ticker: str,
    entity_id: str,
    records: list,
    mcap_data: dict,
) -> int:
    """Store daily price records, skip duplicates."""
    stored = 0
    mcap = mcap_data.get("market_cap")
    shares = mcap_data.get("shares_outstanding")

    for rec in records:
        # Check for existing record (upsert)
        existing = (await session.exec(
            select(DailyPrice).where(
                DailyPrice.ticker == ticker,
                DailyPrice.trade_date == rec["trade_date"],
            )
        )).first()

        if existing:
            # Update with latest data
            for key, val in rec.items():
                if val is not None:
                    setattr(existing, key, val)
            existing.entity_id = entity_id
            if mcap:
                existing.market_cap = mcap
            if shares:
                existing.shares_outstanding = shares
            # Update micro flag with real mcap
            if mcap and rec.get("close"):
                existing.is_micro = rec["close"] < 50.0 and mcap < 500_000_000
            session.add(existing)
        else:
            price = DailyPrice(
                entity_id=entity_id,
                ticker=ticker,
                trade_date=rec["trade_date"],
                open=rec.get("open"),
                high=rec.get("high"),
                low=rec.get("low"),
                close=rec.get("close"),
                volume=rec.get("volume"),
                market_cap=mcap,
                shares_outstanding=shares,
                change_pct=rec.get("change_pct"),
                change_5d_pct=rec.get("change_5d_pct"),
                change_20d_pct=rec.get("change_20d_pct"),
                avg_volume_10d=rec.get("avg_volume_10d"),
                avg_volume_30d=rec.get("avg_volume_30d"),
                is_penny=rec.get("is_penny", False),
                is_micro=(
                    rec.get("close", 999) < 50.0 and
                    (mcap or 999_999_999) < 500_000_000
                ) if mcap else rec.get("is_micro", False),
            )
            session.add(price)
            stored += 1

    return stored


async def propagate_market_caps(
    session: AsyncSession,
    ticker: str,
    entity_id: str,
    mcap: float,
    shares: float,
    latest_close: float,
    avg_vol_30d: float,
    short_data: Optional[dict] = None,
):
    """Push real market cap + short interest into scoring tables."""
    # Update fundamental_scores
    fs = (await session.exec(
        select(FundamentalScore).where(FundamentalScore.entity_id == entity_id)
    )).first()
    if fs:
        fs.market_cap_usd = mcap
        fs.updated_at = datetime.utcnow()
        session.add(fs)

    # Update equity_screens with market cap + short interest
    es = (await session.exec(
        select(EquityScreen).where(EquityScreen.entity_id == entity_id)
    )).first()
    if es:
        es.market_cap_usd = mcap
        es.shares_outstanding = shares
        if short_data:
            if short_data.get("float_shares"):
                es.float_shares = short_data["float_shares"]
            if short_data.get("shares_short"):
                es.short_interest = short_data["shares_short"]
            if short_data.get("short_pct_float"):
                es.short_pct_float = short_data["short_pct_float"]
            if short_data.get("short_ratio"):
                es.days_to_cover = short_data["short_ratio"]
        es.updated_at = datetime.utcnow()
        session.add(es)


async def run_price_ingestion():
    """Main daily price ingestion run."""
    logger.info("=" * 60)
    logger.info("PRICE INGESTION — Starting daily run")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        entities = await get_all_tickers(session)
        logger.info(f"Found {len(entities)} public entities with tickers")

        if not entities:
            logger.info("No tickers to fetch. Run universe discovery first.")
            return

        # Build ticker→entity map
        ticker_map = {}
        all_tickers = []
        for e in entities:
            t = e.ticker.upper().strip()
            ticker_map[t] = e
            all_tickers.append(t)

        # ── Step 1: Batch fetch OHLCV ──────────────────────
        logger.info(f"Fetching OHLCV for {len(all_tickers)} tickers...")
        price_data = fetch_batch_prices(all_tickers, period="35d")
        logger.info(f"Got price data for {len(price_data)} tickers")

        # ── Step 2: Fetch market caps (slower, per-ticker) ──
        # Only fetch for tickers we got price data for
        active_tickers = list(price_data.keys())
        logger.info(f"Fetching market caps for {len(active_tickers)} active tickers...")

        mcap_data = {}
        for i in range(0, len(active_tickers), MCAP_BATCH):
            batch = active_tickers[i:i + MCAP_BATCH]
            batch_mcaps = fetch_market_caps(batch)
            mcap_data.update(batch_mcaps)
            await asyncio.sleep(0.5)  # Rate limit

        logger.info(f"Got market cap data for {len(mcap_data)} tickers")

        # ── Step 3: Store everything ───────────────────────
        total_stored = 0
        propagated = 0
        errors = 0

        for ticker, records in price_data.items():
            entity = ticker_map.get(ticker)
            if not entity:
                continue

            try:
                mcap_info = mcap_data.get(ticker, {})
                stored = await store_prices(
                    session, ticker, entity.id, records, mcap_info,
                )
                total_stored += stored

                # Propagate market cap + short interest to scoring tables
                mcap = mcap_info.get("market_cap")
                shares = mcap_info.get("shares_outstanding")
                if mcap and records:
                    latest = records[-1]
                    short_data = {
                        "float_shares": mcap_info.get("float_shares"),
                        "shares_short": mcap_info.get("shares_short"),
                        "short_pct_float": mcap_info.get("short_pct_float"),
                        "short_ratio": mcap_info.get("short_ratio"),
                    }
                    await propagate_market_caps(
                        session, ticker, entity.id,
                        mcap, shares or 0,
                        latest.get("close", 0),
                        latest.get("avg_volume_30d", 0),
                        short_data=short_data,
                    )
                    propagated += 1

            except Exception as e:
                logger.error(f"Error storing prices for {ticker}: {e}")
                errors += 1

        await session.commit()

        logger.info("=" * 60)
        logger.info(f"PRICE INGESTION COMPLETE")
        logger.info(f"  Tickers fetched: {len(price_data)}")
        logger.info(f"  Price rows stored: {total_stored}")
        logger.info(f"  Market caps propagated: {propagated}")
        logger.info(f"  Errors: {errors}")
        logger.info("=" * 60)


# ═══════════════════════════════════════════════════════════
# 2. UNIVERSE DISCOVERY
# ═══════════════════════════════════════════════════════════

async def run_universe_discovery():
    """
    Discover new public companies from the SEC ticker list.
    Strategy: batch OHLCV download (fast) → filter by price < $50 → create entities.
    Market caps are fetched later during daily price ingestion.
    """
    logger.info("=" * 60)
    logger.info("UNIVERSE DISCOVERY — Scanning SEC ticker list")
    logger.info("=" * 60)

    await create_db_and_tables()

    # Fetch SEC universe
    sec_tickers = fetch_universe_tickers_sec()
    if not sec_tickers:
        logger.error("Failed to fetch SEC ticker list")
        return

    logger.info(f"SEC universe: {len(sec_tickers)} companies")

    async with AsyncSessionLocal() as session:
        # Get existing tickers
        existing = (await session.exec(
            select(Entity.ticker).where(Entity.ticker.isnot(None))  # type: ignore
        )).all()
        existing_tickers = {t.upper() for t in existing if t}
        logger.info(f"Already tracking: {len(existing_tickers)} tickers")

        # Find new tickers
        new_entries = [
            e for e in sec_tickers
            if e["ticker"] and e["ticker"].upper() not in existing_tickers
        ]
        logger.info(f"New tickers to evaluate: {len(new_entries)}")

        if not new_entries:
            logger.info("No new tickers. Universe is up to date.")
            return

        # Step 1: Fast batch OHLCV to get prices (100+ tickers at a time)
        new_tickers = [e["ticker"].upper() for e in new_entries[:UNIVERSE_MAX]]
        logger.info(f"Batch-fetching prices for {len(new_tickers)} tickers...")
        price_data = fetch_batch_prices(new_tickers, period="5d")
        logger.info(f"Got price data for {len(price_data)} tickers")

        # Step 2: Filter by price < $50 (micro-cap candidates)
        # Tickers with no price data are excluded (likely delisted/inactive)
        under_50 = {}
        for ticker, records in price_data.items():
            if records:
                latest_close = records[-1].get("close", 999)
                if latest_close < 50.0:
                    under_50[ticker] = latest_close

        logger.info(f"Tickers under $50: {len(under_50)}")

        # Build a lookup from ticker → SEC entry
        sec_lookup = {e["ticker"].upper(): e for e in new_entries}

        # Step 3: Create entities for sub-$50 stocks
        created = 0
        for ticker, close in under_50.items():
            sec_entry = sec_lookup.get(ticker, {})
            try:
                entity = Entity(
                    name=sec_entry.get("company_name") or ticker,
                    ticker=ticker,
                    cik=sec_entry.get("cik"),
                    entity_type="public",
                )
                session.add(entity)
                created += 1
            except Exception as e:
                logger.debug(f"Entity creation failed for {ticker}: {e}")

        await session.commit()

        logger.info("=" * 60)
        logger.info(f"UNIVERSE DISCOVERY COMPLETE")
        logger.info(f"  SEC universe: {len(sec_tickers)}")
        logger.info(f"  Already tracked: {len(existing_tickers)}")
        logger.info(f"  Price data found: {len(price_data)}")
        logger.info(f"  Under $50: {len(under_50)}")
        logger.info(f"  New entities created: {created}")
        logger.info("=" * 60)


# ═══════════════════════════════════════════════════════════
# 3. MAIN LOOP
# ═══════════════════════════════════════════════════════════

async def run_loop():
    """
    Daily loop:
      - Every day: price ingestion
      - Every Sunday: universe discovery (find new micro-caps)
    """
    cycle = 0
    while True:
        try:
            today = datetime.utcnow()

            # Universe discovery: run on first cycle and every Sunday
            if cycle == 0 or today.weekday() == 6:
                await run_universe_discovery()
                await asyncio.sleep(5)

            # Daily price ingestion
            await run_price_ingestion()

        except Exception as e:
            logger.error(f"Price ingestion cycle failed: {e}")

        cycle += 1

        # Sleep until next run
        # If market is open (weekday), run again in 6 hours for mid-day update
        # Otherwise, sleep until next day
        now = datetime.utcnow()
        if now.weekday() < 5 and 14 <= now.hour < 22:
            wait = 6 * 3600
            logger.info("Market hours — next update in 6 hours")
        else:
            wait = 24 * 3600
            logger.info("Next price ingestion in 24 hours")

        await asyncio.sleep(wait)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        asyncio.run(run_price_ingestion())
    elif mode == "discover":
        asyncio.run(run_universe_discovery())
    else:
        asyncio.run(run_loop())
