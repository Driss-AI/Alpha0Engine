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
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.daily_prices import DailyPrice
from shared.schemas.fundamentals import FundamentalScore
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.signals import Signal
from shared.universe import (
    EXCLUDED_ENTITY_TYPE,
    SCANNABLE_ENTITY_TYPE,
    classify_security,
    entity_type_for,
)

from price_fetcher import fetch_batch_prices, fetch_market_caps, fetch_universe_tickers_sec
from stooq_fallback import fetch_stooq_quotes, fetch_sec_shares_outstanding
from finnhub_quotes import fetch_finnhub_quotes, fetch_finnhub_profiles
from fmp_data import (
    fetch_fmp_float,
    fetch_fmp_market_caps,
    fetch_fmp_quotes,
    is_configured as fmp_configured,
)
from volume_signals import detect_volume_signals

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

        # ── Step 0: FMP, when configured ───────────────────
        # The only source here that returns real VOLUME for the whole universe,
        # batched 100 symbols at a time. Everything below it is a fallback that
        # exists because Yahoo blocks cloud IPs.
        price_data: dict = {}
        fmp_mcaps: dict = {}
        if fmp_configured():
            price_data.update(fetch_fmp_quotes(all_tickers))
            fmp_mcaps = fetch_fmp_market_caps(list(price_data.keys()))
            logger.info(f"Price coverage after FMP: {len(price_data)}/{len(all_tickers)}")
        else:
            logger.info("FMP_API_KEY not set — falling back to Yahoo/Stooq/Finnhub "
                        "(no volume, no float: lenses 4 and 5 stay starved)")

        # ── Step 1: Batch fetch OHLCV ──────────────────────
        still_unpriced = [t for t in all_tickers if t not in price_data]
        logger.info(f"Fetching OHLCV for {len(still_unpriced)} tickers...")
        yahoo_tickers = set()
        for _t, _recs in fetch_batch_prices(still_unpriced, period="35d").items():
            price_data.setdefault(_t, _recs)
            yahoo_tickers.add(_t)
        logger.info(f"Got price data for {len(price_data)} tickers")

        # ── Step 1b: Stooq fallback for whatever Yahoo blocked ──
        # Yahoo blocks cloud IPs wholesale some days (observed: 0 rows stored).
        # Stooq gives a keyless EOD snapshot for the missing tickers so the
        # engine never runs priceless.
        missing = [t for t in all_tickers if t not in price_data]
        if missing:
            logger.info(f"Stooq fallback for {len(missing)} tickers Yahoo returned nothing for...")
            price_data.update(fetch_stooq_quotes(missing))
            logger.info(f"Price coverage after Stooq: {len(price_data)}/{len(all_tickers)}")

        # ── Step 1c: Finnhub last resort (rate-limited, budget-capped) ──
        # Signal-bearing entities first: they are the ones the screener can
        # actually score, so the budget goes where it matters.
        still_missing = [t for t in all_tickers if t not in price_data]
        if still_missing:
            signal_eids = set(
                (await session.exec(select(Signal.entity_id).distinct())).all()
            )
            still_missing.sort(
                key=lambda t: (ticker_map[t].id not in signal_eids)
            )
            price_data.update(fetch_finnhub_quotes(still_missing))
            logger.info(f"Price coverage after Finnhub: {len(price_data)}/{len(all_tickers)}")

        # ── Step 2: Market caps ─────────────────────────────
        # yfinance .info only for tickers Yahoo actually served (1s/ticker —
        # pointless against blocked tickers). Everything else gets
        # close x SEC shares outstanding below.
        active_tickers = sorted(yahoo_tickers)
        logger.info(f"Fetching market caps for {len(active_tickers)} yahoo-served tickers...")

        mcap_data = dict(fmp_mcaps)
        for i in range(0, len(active_tickers), MCAP_BATCH):
            batch = active_tickers[i:i + MCAP_BATCH]
            # Merge field-wise: yfinance carries float/short that FMP's quote
            # doesn't, but a blocked .info call returns blanks that must not
            # wipe a market cap FMP already supplied.
            for t, info in fetch_market_caps(batch).items():
                merged = mcap_data.setdefault(t, {})
                for k, v in info.items():
                    if v is not None:
                        merged[k] = v
            await asyncio.sleep(0.5)  # Rate limit

        logger.info(f"Got market cap data for {len(mcap_data)} tickers")

        # ── Step 2b: SEC-shares market caps for the rest ────
        need_mcap = [t for t in price_data if not mcap_data.get(t, {}).get("market_cap")]
        if need_mcap:
            sec_shares = fetch_sec_shares_outstanding()
            filled = 0
            for t in need_mcap:
                entity = ticker_map.get(t)
                cik = str(int(entity.cik)) if entity and entity.cik and entity.cik.isdigit() else None
                shares = sec_shares.get(cik) if cik else None
                close = price_data[t][-1].get("close") if price_data[t] else None
                if shares and close:
                    info = mcap_data.setdefault(t, {})
                    info["market_cap"] = round(close * shares, 0)
                    info["shares_outstanding"] = shares
                    filled += 1
            logger.info(f"SEC-shares market caps filled for {filled}/{len(need_mcap)} tickers")

        # ── Step 2c: Finnhub profiles for caps still missing ─
        # (SEC frames are sparse — a single quarter covers ~700 filers.)
        still_capless = [t for t in price_data
                         if not mcap_data.get(t, {}).get("market_cap")]
        if still_capless:
            for t, info in fetch_finnhub_profiles(still_capless).items():
                merged = mcap_data.setdefault(t, {})
                for k, v in info.items():
                    if v and not merged.get(k):
                        merged[k] = v
            with_cap = sum(1 for t in price_data
                           if mcap_data.get(t, {}).get("market_cap"))
            logger.info(f"Market-cap coverage after Finnhub profiles: "
                        f"{with_cap}/{len(price_data)} priced tickers")

        # ── Step 2d: FMP float — the input lens 4 never had ─
        # One call per symbol, so spend the budget on the smallest caps first:
        # a tiny float is only interesting on a tiny company, and those are the
        # names the engine exists to find.
        if fmp_configured():
            need_float = [t for t in price_data
                          if not mcap_data.get(t, {}).get("float_shares")]
            need_float.sort(
                key=lambda t: mcap_data.get(t, {}).get("market_cap") or float("inf")
            )
            for t, info in fetch_fmp_float(need_float).items():
                merged = mcap_data.setdefault(t, {})
                for k, v in info.items():
                    if v and not merged.get(k):
                        merged[k] = v
                merged["float_source"] = "fmp"
            with_float = sum(1 for t in price_data
                             if mcap_data.get(t, {}).get("float_shares"))
            logger.info(f"Float coverage after FMP: "
                        f"{with_float}/{len(price_data)} priced tickers")

        # ── Step 3: Store everything ───────────────────────
        total_stored = 0
        propagated = 0
        errors = 0
        volume_signals_emitted = 0

        for ticker, records in price_data.items():
            entity = ticker_map.get(ticker)
            if not entity:
                continue

            try:
                mcap_info = mcap_data.get(ticker, {})

                # Backfill entity business description + sector (fill-if-empty).
                # This is the text the lane router + demand lens match against —
                # without it, public names like BE carry no megatrend keywords and
                # match no lane. Reuses the .info we already fetched (no extra call).
                enriched = False
                bsum = mcap_info.get("business_summary")
                if bsum and not getattr(entity, "description", None):
                    entity.description = bsum
                    enriched = True
                if mcap_info.get("sector") and not entity.sector:
                    entity.sector = mcap_info.get("sector")
                    enriched = True
                if mcap_info.get("industry") and not entity.subsector:
                    entity.subsector = mcap_info.get("industry")
                    enriched = True
                if enriched:
                    session.add(entity)

                stored = await store_prices(
                    session, ticker, entity.id, records, mcap_info,
                )
                total_stored += stored

                # ── Sprint 8.8: volume awakening / breakout detection ──
                if records:
                    latest = records[-1]
                    for vs in detect_volume_signals(latest):
                        sig_date = latest.get("trade_date") or datetime.utcnow()
                        src_id = f"{ticker}:{vs['signal_type']}:{sig_date}"
                        exists = (await session.exec(
                            select(Signal).where(
                                Signal.source_id == src_id,
                                Signal.signal_type == vs["signal_type"],
                            )
                        )).first()
                        if exists:
                            continue
                        session.add(Signal(
                            entity_id=entity.id,
                            signal_type=vs["signal_type"],
                            signal_date=sig_date if isinstance(sig_date, datetime)
                                        else datetime.utcnow(),
                            value=vs["value"],
                            raw_data={**vs["detail"], "ticker": ticker, "source": "prices"},
                            source="ingest_prices",
                            source_id=src_id,
                            notes=f"{vs['signal_type']} on {ticker}: {vs['detail']}",
                        ))
                        volume_signals_emitted += 1

                # ── Float snapshot signal — real float/short interest for the
                # float-mechanics lens (and, over time, a float/short time
                # series for backtests). One row per day. Float comes from FMP
                # where configured, else yfinance where it isn't blocked.
                if mcap_info.get("float_shares") or mcap_info.get("shares_short"):
                    snap_date = datetime.utcnow().strftime("%Y-%m-%d")
                    src_id = f"float:{ticker}:{snap_date}"
                    exists = (await session.exec(
                        select(Signal).where(
                            Signal.source_id == src_id,
                            Signal.signal_type == "float_snapshot",
                        )
                    )).first()
                    if not exists:
                        session.add(Signal(
                            entity_id=entity.id,
                            signal_type="float_snapshot",
                            signal_date=datetime.utcnow(),
                            value=0.0,  # informational — lens reads raw_data
                            raw_data={
                                "ticker": ticker,
                                "float_shares": mcap_info.get("float_shares"),
                                "short_interest": mcap_info.get("shares_short"),
                                "short_pct_float": mcap_info.get("short_pct_float"),
                                "days_to_cover": mcap_info.get("short_ratio"),
                                "shares_outstanding": mcap_info.get("shares_outstanding"),
                                "source": mcap_info.get("float_source") or "yfinance",
                            },
                            source="ingest_prices",
                            source_id=src_id,
                            notes=f"float snapshot {ticker}: "
                                  f"float={mcap_info.get('float_shares')}, "
                                  f"short%={mcap_info.get('short_pct_float')}",
                        ))

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
        logger.info(f"  Volume/breakout signals: {volume_signals_emitted}")
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

        # Create entities directly from SEC ticker list.
        # No price filtering here — daily price ingestion handles that.
        # This ensures the entity table is populated so all other
        # pipelines (Form 4, trials, 8-K, screener) have data to work with.
        #
        # Securities that can never be a micro-cap explosion candidate (SPAC
        # warrants/units/rights, preferreds, unsponsored foreign ADRs) are still
        # recorded, but with an entity_type the scanners don't select — so they
        # never consume screener time or the capped Finnhub price budget.
        created = 0
        excluded = 0
        for entry in new_entries[:UNIVERSE_MAX]:
            ticker = entry["ticker"].upper().strip()
            if not ticker or len(ticker) > 10:
                continue
            name = entry.get("company_name") or ticker
            etype = entity_type_for(ticker, name)
            try:
                entity = Entity(
                    name=name,
                    ticker=ticker,
                    cik=entry.get("cik"),
                    entity_type=etype,
                )
                session.add(entity)
                created += 1
                if etype == EXCLUDED_ENTITY_TYPE:
                    excluded += 1
            except Exception as e:
                logger.debug(f"Entity creation failed for {ticker}: {e}")

            # Commit in batches to avoid memory issues
            if created % 500 == 0 and created > 0:
                await session.commit()
                logger.info(f"  Created {created} entities so far...")

        await session.commit()

        reclassified = await reclassify_existing_universe(session)

        logger.info("=" * 60)
        logger.info(f"UNIVERSE DISCOVERY COMPLETE")
        logger.info(f"  SEC universe: {len(sec_tickers)}")
        logger.info(f"  Already tracked: {len(existing_tickers)}")
        logger.info(f"  New entities created: {created} "
                    f"({created - excluded} scannable, {excluded} excluded)")
        logger.info(f"  Existing entities reclassified: {reclassified}")
        logger.info("=" * 60)


async def reclassify_existing_universe(session: AsyncSession) -> int:
    """Re-apply the security filter to entities already in the database.

    Discovery used to store every SEC ticker as `public`, so the table still
    holds thousands of warrants, units, rights and ADRs that the screener dutifully
    scores every run. This corrects them in place (both directions, so a security
    wrongly excluded by an earlier rule is restored once the rule improves).
    """
    rows = (await session.exec(
        select(Entity).where(Entity.ticker.isnot(None))  # type: ignore[union-attr]
    )).all()

    changed = 0
    by_reason: dict[str, int] = {}
    for ent in rows:
        want = entity_type_for(ent.ticker, ent.name)
        # Only ever move between the two types this filter owns — never clobber
        # a hand-set type like "private".
        if ent.entity_type not in (SCANNABLE_ENTITY_TYPE, EXCLUDED_ENTITY_TYPE):
            continue
        if ent.entity_type == want:
            continue
        if want == EXCLUDED_ENTITY_TYPE:
            reason = classify_security(ent.ticker, ent.name)
            by_reason[reason] = by_reason.get(reason, 0) + 1
        else:
            by_reason["restored"] = by_reason.get("restored", 0) + 1
        ent.entity_type = want
        session.add(ent)
        changed += 1
        if changed % 500 == 0:
            await session.commit()

    await session.commit()
    if changed:
        logger.info(f"  Reclassified {changed} existing entities: {by_reason}")
    return changed


# ═══════════════════════════════════════════════════════════
# 3. MAIN LOOP
# ═══════════════════════════════════════════════════════════

async def run_loop():
    """
    Daily loop:
      - Every day: price ingestion
      - Every Sunday: universe discovery (find new micro-caps)
    """
    import time as _time
    from shared.clients.heartbeat import report_heartbeat

    cycle = 0
    while True:
        _start = _time.time()
        try:
            today = datetime.utcnow()

            # Universe discovery: run on first cycle and every Sunday
            if cycle == 0 or today.weekday() == 6:
                await run_universe_discovery()
                await asyncio.sleep(5)

            # Daily price ingestion
            await run_price_ingestion()

            _dur = _time.time() - _start
            await report_heartbeat("ingest-prices", records=0, duration_seconds=_dur, interval_hours=24)

        except Exception as e:
            logger.error(f"Price ingestion cycle failed: {e}")
            await report_heartbeat("ingest-prices", error=str(e), interval_hours=24)

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
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-prices", run_price_ingestion))
    elif mode == "discover":
        asyncio.run(run_universe_discovery())
    else:
        asyncio.run(run_loop())
