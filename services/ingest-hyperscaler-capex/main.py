"""
Hyperscaler Capex Ingestion Worker (Sprint 8.4) — L1 AI Infrastructure lane

Tracks quarterly capex for MSFT/GOOGL/META/AMZN/ORCL via yfinance quarterly
cash-flow statements. A YoY capex inflection (>30%) is a leading demand signal
for the entire AI-infra supply chain (power, data centers, optical, memory).

Emits a `hyperscaler_capex_inflection` signal (attached to a synthetic
"hyperscaler-capex" source) when an inflection quarter is detected, and upserts
`hyperscaler_capex` rows. The screener's demand-rider lens reads these.

Runs daily (data only changes quarterly, but cheap to re-check).
"""
import os
import sys
import asyncio
import logging
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.hyperscaler_capex import HyperscalerCapex, HYPERSCALERS
from shared.schemas.market_context import MarketContextSignal

from capex_analyzer import build_capex_records, derive_market_context

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-hyperscaler-capex")

COMPANY_NAMES = {
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "META": "Meta Platforms",
    "AMZN": "Amazon", "ORCL": "Oracle",
}


def fetch_quarterly_capex(ticker: str) -> list[dict]:
    """Fetch quarterly capex points from yfinance.

    Returns [{"year": int, "quarter": int, "capex_usd": float}, ...].
    Isolated here so capex_analyzer stays network-free and testable.
    """
    import yfinance as yf

    points: list[dict] = []
    try:
        tk = yf.Ticker(ticker)
        cf = tk.quarterly_cashflow
        if cf is None or cf.empty:
            return []
        # Row label varies: "Capital Expenditure" / "Capital Expenditures"
        row_label = None
        for candidate in ("Capital Expenditure", "Capital Expenditures"):
            if candidate in cf.index:
                row_label = candidate
                break
        if row_label is None:
            return []
        series = cf.loc[row_label]
        for ts, val in series.items():
            if val is None:
                continue
            try:
                year = ts.year
                quarter = (ts.month - 1) // 3 + 1
                points.append({"year": int(year), "quarter": int(quarter),
                               "capex_usd": float(val)})
            except (AttributeError, ValueError, TypeError):
                continue
    except Exception as e:
        logger.error(f"yfinance capex fetch failed for {ticker}: {e}")
    return points


async def _upsert_capex(session: AsyncSession, rec: dict) -> bool:
    """Upsert one hyperscaler_capex row. Returns True if inflection (new)."""
    existing = (await session.exec(
        select(HyperscalerCapex).where(
            HyperscalerCapex.ticker == rec["ticker"],
            HyperscalerCapex.fiscal_period == rec["fiscal_period"],
        )
    )).first()

    was_inflection = bool(existing and existing.is_inflection)

    if existing:
        existing.capex_usd = rec["capex_usd"]
        existing.capex_yoy_pct = rec["capex_yoy_pct"]
        existing.is_inflection = rec["is_inflection"]
        existing.company = rec["company"]
        session.add(existing)
    else:
        session.add(HyperscalerCapex(
            ticker=rec["ticker"], company=rec["company"],
            fiscal_period=rec["fiscal_period"], capex_usd=rec["capex_usd"],
            capex_yoy_pct=rec["capex_yoy_pct"], is_inflection=rec["is_inflection"],
            source_url="https://finance.yahoo.com/quote/%s/cash-flow" % rec["ticker"],
        ))

    # Newly-detected inflection (not previously flagged)
    return rec["is_inflection"] and not was_inflection


async def _upsert_market_context(session: AsyncSession, ctx: dict) -> None:
    """Upsert the market-wide capex-inflection context row (S11.3).

    Keeps exactly one active row per context_type: the latest inflecting period
    is marked active; any earlier period of the same type is deactivated so the
    demand-rider lens only ever reads the current macro state.
    """
    existing = (await session.exec(
        select(MarketContextSignal).where(
            MarketContextSignal.context_type == ctx["context_type"],
            MarketContextSignal.period == ctx["period"],
        )
    )).first()

    if existing:
        existing.value = ctx["value"]
        existing.lane_id = ctx["lane_id"]
        existing.is_active = True
        existing.details = ctx["details"]
        existing.as_of_date = date.today()
        session.add(existing)
    else:
        session.add(MarketContextSignal(
            context_type=ctx["context_type"],
            lane_id=ctx["lane_id"],
            value=ctx["value"],
            period=ctx["period"],
            source=ctx["source"],
            is_active=True,
            details=ctx["details"],
            as_of_date=date.today(),
        ))

    # Deactivate stale rows of the same type from earlier periods.
    stale = (await session.exec(
        select(MarketContextSignal).where(
            MarketContextSignal.context_type == ctx["context_type"],
            MarketContextSignal.period != ctx["period"],
            MarketContextSignal.is_active == True,  # noqa: E712
        )
    )).all()
    for row in stale:
        row.is_active = False
        session.add(row)


async def run_capex_ingestion():
    """Daily hyperscaler capex ingestion."""
    logger.info("=" * 60)
    logger.info("HYPERSCALER CAPEX INGESTION — Starting")
    logger.info("=" * 60)

    await create_db_and_tables()

    total_rows = 0
    new_inflections = 0
    all_records: list[dict] = []

    async with AsyncSessionLocal() as session:
        for ticker in HYPERSCALERS:
            company = COMPANY_NAMES.get(ticker, ticker)
            points = fetch_quarterly_capex(ticker)
            if not points:
                logger.warning(f"No capex data for {ticker}")
                continue
            records = build_capex_records(ticker, company, points)
            all_records.extend(records)
            for rec in records:
                try:
                    is_new_inflection = await _upsert_capex(session, rec)
                    total_rows += 1
                    if is_new_inflection:
                        new_inflections += 1
                        logger.info(
                            f"  ★ {ticker} {rec['fiscal_period']} capex inflection: "
                            f"+{rec['capex_yoy_pct']:.0%} YoY (${rec['capex_usd']/1e9:.1f}B)"
                        )
                except Exception as e:
                    logger.error(f"capex upsert failed {ticker} {rec['fiscal_period']}: {e}")
            logger.info(f"{ticker}: {len(records)} quarters processed")

        # S11.3: reduce to a market-wide context signal the demand-rider lens reads.
        context = derive_market_context(all_records)
        if context is not None:
            try:
                await _upsert_market_context(session, context)
                logger.info(
                    f"  ⇪ market context: {context['context_type']} {context['period']} "
                    f"+{context['value']:.0%} YoY ({', '.join(context['details']['inflecting_tickers'])})"
                )
            except Exception as e:
                logger.error(f"market context upsert failed: {e}")
        else:
            logger.info("No active capex inflection — no market context written")

        await session.commit()

    logger.info("=" * 60)
    logger.info(f"CAPEX INGESTION COMPLETE — {total_rows} rows, {new_inflections} new inflections")
    logger.info("=" * 60)
    return {
        "records_processed": total_rows,
        "metadata": {
            "new_inflections": new_inflections,
            "market_context": context["period"] if context else None,
        },
    }


async def run_loop():
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_capex_ingestion()
            await report_heartbeat("ingest-hyperscaler-capex", duration_seconds=_time.time() - _start, interval_hours=24)
        except Exception as e:
            logger.error(f"Capex ingestion failed: {e}")
            await report_heartbeat("ingest-hyperscaler-capex", error=str(e), interval_hours=24)
        logger.info("Next capex ingestion in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-hyperscaler-capex", run_capex_ingestion))
    else:
        asyncio.run(run_loop())
