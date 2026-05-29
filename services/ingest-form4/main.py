"""
Form 4 Insider Transaction Worker
====================================
Activates Lens 5 (Smart Money) with real insider buy/sell data.

Pipeline:
  1. Get tracked entities with CIKs
  2. For each, check SEC EDGAR recent filings for Form 4s
  3. Download and parse the XML
  4. Create signals: signal_type="form_4_insider"
  5. Raw data includes: insider name, title, shares, price, value, buy/sell

Data source: SEC EDGAR (free, 10 req/sec, User-Agent required)
  - Filing index: https://data.sec.gov/submissions/CIK{padded}.json
  - Filing XML: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal

from form4_parser import parse_form4_xml

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-form4")

SEC_BASE = "https://data.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}
XML_HEADERS = {"User-Agent": EDGAR_UA, "Accept": "text/xml, application/xml"}

SEC_DELAY = 0.12  # 10 req/sec limit
LOOKBACK_DAYS = 30  # How far back to check for new Form 4s
ENTITY_BATCH = 50


async def get_recent_form4_filings(
    client: httpx.AsyncClient,
    cik: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> List[Dict[str, Any]]:
    """
    Get recent Form 4 filing accession numbers for a CIK.
    Uses the SEC submissions endpoint.
    """
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/submissions/CIK{cik_padded}.json"

    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return []

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        filings = []
        for i in range(len(forms)):
            form = forms[i] if i < len(forms) else ""
            if form not in ("4", "4/A"):
                continue

            filing_date = dates[i] if i < len(dates) else ""
            if filing_date < cutoff:
                continue

            accession = accessions[i] if i < len(accessions) else ""
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""

            if accession and primary_doc:
                filings.append({
                    "accession": accession,
                    "primary_doc": primary_doc,
                    "filing_date": filing_date,
                    "cik": cik,
                })

        return filings

    except Exception as e:
        logger.debug(f"Submissions fetch failed for CIK {cik}: {e}")
        return []


async def download_form4_xml(
    client: httpx.AsyncClient,
    cik: str,
    accession: str,
    primary_doc: str,
) -> Optional[str]:
    """Download the Form 4 XML document."""
    # Accession number format: 0001234567-24-000001 → 000123456724000001
    accession_path = accession.replace("-", "")
    url = f"{SEC_ARCHIVES}/{cik}/{accession_path}/{primary_doc}"

    try:
        resp = await client.get(url, headers=XML_HEADERS)
        if resp.status_code == 200:
            return resp.text
        logger.debug(f"Form 4 XML download returned {resp.status_code} for {url}")
        return None
    except Exception as e:
        logger.debug(f"Form 4 XML download failed: {e}")
        return None


async def check_existing_signal(
    session: AsyncSession, entity_id: str, source_id: str,
) -> bool:
    """Check if we already ingested this Form 4 filing."""
    result = await session.exec(
        select(Signal).where(
            Signal.entity_id == entity_id,
            Signal.source_id == source_id,
        )
    )
    return result.first() is not None


def _compute_signal_value(parsed: Dict[str, Any]) -> float:
    """
    Signal value based on transaction type and size.
    Buys = bullish (positive), Sells = bearish (negative-ish).
    Cluster buys by officers = strongest signal.
    """
    if parsed["buy_count"] > 0 and parsed["sell_count"] == 0:
        # Pure buy — bullish
        base = 0.6
        if parsed["total_buy_value"] > 100_000:
            base = 0.75
        if parsed["total_buy_value"] > 500_000:
            base = 0.85
        if parsed["total_buy_value"] > 1_000_000:
            base = 0.90
        # Officer/Director bonus
        if parsed["insider_relationship"] in ("Officer", "Director"):
            base = min(base + 0.05, 0.95)
        return base
    elif parsed["sell_count"] > 0 and parsed["buy_count"] == 0:
        # Pure sell — mildly bearish (insiders sell for many reasons)
        return 0.25
    elif parsed["buy_count"] > 0 and parsed["sell_count"] > 0:
        # Mixed — look at net
        if parsed["net_value"] > 0:
            return 0.55  # Net buyer
        return 0.35  # Net seller
    return 0.3  # Grants, exercises only


async def run_form4_ingestion():
    """Main daily Form 4 ingestion run."""
    logger.info("=" * 60)
    logger.info("FORM 4 INSIDER INGESTION — Starting daily run")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Get all public entities with CIKs
        entities = (await session.exec(
            select(Entity).where(
                Entity.entity_type == "public",
                Entity.cik.isnot(None),  # type: ignore
            ).limit(5000)
        )).all()

        logger.info(f"Checking Form 4 filings for {len(entities)} entities")

        if not entities:
            logger.info("No entities with CIKs. Exiting.")
            return

        total_filings = 0
        signals_created = 0
        buys_detected = 0
        sells_detected = 0
        errors = 0

        async with httpx.AsyncClient(timeout=30) as client:
            for batch_start in range(0, len(entities), ENTITY_BATCH):
                batch = entities[batch_start:batch_start + ENTITY_BATCH]

                for entity in batch:
                    cik = entity.cik
                    if not cik:
                        continue

                    try:
                        # Get recent Form 4 filings
                        filings = await get_recent_form4_filings(client, cik)
                        await asyncio.sleep(SEC_DELAY)

                        if not filings:
                            continue

                        total_filings += len(filings)

                        for filing in filings[:10]:  # Cap per entity
                            accession = filing["accession"]
                            source_id = f"form4:{accession}"

                            # Skip if already ingested
                            if await check_existing_signal(session, entity.id, source_id):
                                continue

                            # Download and parse
                            xml = await download_form4_xml(
                                client, cik, accession, filing["primary_doc"],
                            )
                            await asyncio.sleep(SEC_DELAY)

                            if not xml:
                                continue

                            parsed = parse_form4_xml(xml)
                            if not parsed or not parsed["transactions"]:
                                continue

                            # Create signal
                            signal_value = _compute_signal_value(parsed)
                            filing_date = filing.get("filing_date", "")

                            try:
                                sig_date = datetime.fromisoformat(filing_date)
                            except (ValueError, TypeError):
                                sig_date = datetime.utcnow()

                            # Build notes
                            tx_summary = []
                            if parsed["buy_count"] > 0:
                                tx_summary.append(
                                    f"BUY {parsed['total_buy_shares']:.0f} shares "
                                    f"(${parsed['total_buy_value']:,.0f})"
                                )
                                buys_detected += 1
                            if parsed["sell_count"] > 0:
                                tx_summary.append(
                                    f"SELL {parsed['total_sell_shares']:.0f} shares "
                                    f"(${parsed['total_sell_value']:,.0f})"
                                )
                                sells_detected += 1

                            notes = (
                                f"{parsed['insider_name']} "
                                f"({parsed['insider_title'] or parsed['insider_relationship']}) — "
                                f"{' | '.join(tx_summary)}"
                            )

                            signal = Signal(
                                entity_id=entity.id,
                                signal_type="form_4_insider",
                                signal_date=sig_date,
                                value=signal_value,
                                raw_data={
                                    "insider_name": parsed["insider_name"],
                                    "insider_title": parsed["insider_title"],
                                    "insider_relationship": parsed["insider_relationship"],
                                    "transaction_type": "Purchase" if parsed["buy_count"] > 0 else "Sale",
                                    "shares": parsed["net_shares"],
                                    "shares_held": parsed["transactions"][-1].get("shares_after", 0) if parsed["transactions"] else 0,
                                    "value_usd": parsed["total_buy_value"] or parsed["total_sell_value"],
                                    "transaction_value": parsed["net_value"],
                                    "buy_count": parsed["buy_count"],
                                    "sell_count": parsed["sell_count"],
                                    "issuer_ticker": parsed["issuer_ticker"],
                                    "issuer_cik": parsed["issuer_cik"],
                                    "filing_date": filing_date,
                                    "accession": accession,
                                },
                                source="edgar_form4",
                                source_id=source_id,
                                notes=notes[:500],
                            )
                            session.add(signal)
                            signals_created += 1

                            # Log significant buys
                            if parsed["buy_count"] > 0 and parsed["total_buy_value"] > 50_000:
                                ticker = entity.ticker or parsed["issuer_ticker"] or "?"
                                logger.info(
                                    f"  ★ {ticker} — {parsed['insider_name']} "
                                    f"({parsed['insider_title']}) — "
                                    f"BUY ${parsed['total_buy_value']:,.0f}"
                                )

                    except Exception as e:
                        logger.error(f"Error processing Form 4 for {entity.name}: {e}")
                        errors += 1

                await session.commit()
                logger.info(
                    f"Batch {batch_start // ENTITY_BATCH + 1} committed — "
                    f"{signals_created} signals so far"
                )

    logger.info("=" * 60)
    logger.info(f"FORM 4 INGESTION COMPLETE")
    logger.info(f"  Entities checked: {len(entities)}")
    logger.info(f"  Form 4 filings found: {total_filings}")
    logger.info(f"  Signals created: {signals_created}")
    logger.info(f"  Insider buys: {buys_detected}")
    logger.info(f"  Insider sells: {sells_detected}")
    logger.info(f"  Errors: {errors}")
    logger.info("=" * 60)


async def run_loop():
    """Daily loop."""
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_form4_ingestion()
            await report_heartbeat("ingest-form4", duration_seconds=_time.time()-_start, interval_hours=24)
        except Exception as e:
            logger.error(f"Form 4 ingestion failed: {e}")
            await report_heartbeat("ingest-form4", error=str(e), interval_hours=24)
        logger.info("Next Form 4 ingestion in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        asyncio.run(run_form4_ingestion())
    else:
        asyncio.run(run_loop())
