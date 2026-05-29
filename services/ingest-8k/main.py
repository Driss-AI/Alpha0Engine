"""
8-K Material Event Monitor
==============================
Near-real-time catalyst detection from SEC 8-K filings.
8-Ks are filed within 4 business days of a material event —
FDA results, M&A announcements, contract wins, etc.

Pipeline:
  1. Poll SEC EDGAR EFTS for 8-K filings from yesterday/today
  2. Match CIKs to tracked entities
  3. Download filing text
  4. Classify catalyst type via NLP keywords
  5. Create signals with catalyst_type for Lens 1

Runs every 6 hours during business days, daily on weekends.
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
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal

from filing_classifier import extract_items, classify_catalyst, compute_signal_value, is_catalyst_filing

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-8k")

EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA}
SEC_DELAY = 0.12  # 10 req/sec


async def fetch_8k_filings(
    client: httpx.AsyncClient,
    date_str: str,
) -> List[Dict[str, Any]]:
    """
    Fetch 8-K filings from SEC EDGAR EFTS for a given date.
    Returns list of filing metadata.
    """
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": "",
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": date_str,
        "enddt": date_str,
    }

    try:
        resp = await client.get(url, params=params, headers=HEADERS)
        if resp.status_code != 200:
            logger.error(f"EFTS returned {resp.status_code}")
            return []

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        filings = []

        for hit in hits:
            src = hit.get("_source", {})
            raw_id = hit.get("_id", "")

            ciks = src.get("ciks", [])
            cik = ciks[0] if isinstance(ciks, list) and ciks else ""

            # Parse accession from _id
            accession = ""
            primary_doc = ""
            if ":" in raw_id:
                parts = raw_id.split(":")
                accession = parts[0] if parts else ""
                primary_doc = parts[1] if len(parts) > 1 else ""

            names = src.get("display_names", [])
            company_name = ""
            if names:
                # Format: "Company Name  (CIK 0001234567)"
                company_name = names[0].split("(CIK")[0].strip() if names[0] else ""

            filings.append({
                "cik": cik.lstrip("0"),
                "cik_padded": cik,
                "accession": accession,
                "primary_doc": primary_doc,
                "company_name": company_name,
                "filing_date": src.get("file_date", date_str),
                "form_type": src.get("form_type", "8-K"),
            })

        return filings

    except Exception as e:
        logger.error(f"EFTS fetch failed: {e}")
        return []


async def download_filing_text(
    client: httpx.AsyncClient,
    cik: str,
    accession: str,
    primary_doc: str,
    max_chars: int = 15000,
) -> Optional[str]:
    """Download the 8-K filing text (first N chars for classification)."""
    accession_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{primary_doc}"

    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            text = resp.text[:max_chars]
            # Strip HTML tags for cleaner NLP
            import re
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        return None
    except Exception as e:
        logger.debug(f"Filing download failed: {e}")
        return None


async def run_8k_ingestion():
    """Main 8-K monitoring run."""
    logger.info("=" * 60)
    logger.info("8-K MONITOR — Starting scan")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Build CIK → entity lookup
        entities = (await session.exec(
            select(Entity).where(
                Entity.entity_type == "public",
                Entity.cik.isnot(None),  # type: ignore
            ).limit(10000)
        )).all()

        cik_map = {}
        for e in entities:
            if e.cik:
                cik_map[e.cik.lstrip("0")] = e

        logger.info(f"Tracking {len(cik_map)} entities by CIK")

        if not cik_map:
            logger.info("No entities with CIKs. Exiting.")
            return

        # Scan yesterday and today
        dates = [
            (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"),
            datetime.utcnow().strftime("%Y-%m-%d"),
        ]

        total_filings = 0
        matched = 0
        catalysts_found = 0
        signals_created = 0

        async with httpx.AsyncClient(timeout=30) as client:
            for date_str in dates:
                logger.info(f"Scanning 8-K filings for {date_str}...")
                filings = await fetch_8k_filings(client, date_str)
                total_filings += len(filings)
                logger.info(f"  Found {len(filings)} 8-K filings")
                await asyncio.sleep(SEC_DELAY)

                for filing in filings:
                    cik = filing["cik"]
                    entity = cik_map.get(cik)
                    if not entity:
                        continue

                    matched += 1
                    source_id = f"8k:{filing['accession']}"

                    # Skip if already ingested
                    existing = (await session.exec(
                        select(Signal).where(
                            Signal.entity_id == entity.id,
                            Signal.source_id == source_id,
                        )
                    )).first()
                    if existing:
                        continue

                    # Download and classify
                    text = await download_filing_text(
                        client, filing["cik_padded"],
                        filing["accession"], filing["primary_doc"],
                    )
                    await asyncio.sleep(SEC_DELAY)

                    if not text:
                        continue

                    items = extract_items(text)
                    catalyst = classify_catalyst(text)

                    # Only create signals for meaningful catalysts
                    if not is_catalyst_filing(items, catalyst):
                        continue

                    catalysts_found += 1
                    signal_value = compute_signal_value(items, catalyst)
                    cat_type = catalyst.get("catalyst_type", "8k_event")

                    try:
                        sig_date = datetime.fromisoformat(filing["filing_date"])
                    except (ValueError, TypeError):
                        sig_date = datetime.utcnow()

                    notes = (
                        f"8-K Items {','.join(items)} — "
                        f"{cat_type or 'material event'} "
                        f"(conf: {catalyst.get('confidence', 0):.0%})"
                    )

                    signal = Signal(
                        entity_id=entity.id,
                        signal_type="8k_event" if not cat_type else cat_type.replace("_", "_"),
                        signal_date=sig_date,
                        value=signal_value,
                        raw_data={
                            "items": items,
                            "catalyst_type": cat_type,
                            "catalyst_confidence": catalyst.get("confidence"),
                            "all_catalysts": catalyst.get("all_matches", {}),
                            "company_name": filing["company_name"],
                            "cik": cik,
                            "accession": filing["accession"],
                            "filing_date": filing["filing_date"],
                            "text_preview": text[:500],
                        },
                        source="edgar_8k",
                        source_id=source_id,
                        notes=notes[:500],
                    )
                    session.add(signal)
                    signals_created += 1

                    # Log high-value catalysts
                    if signal_value >= 0.6:
                        ticker = entity.ticker or "?"
                        logger.info(
                            f"  ★ {ticker} — {cat_type} — "
                            f"items: {','.join(items)} — "
                            f"value: {signal_value:.2f}"
                        )

        await session.commit()

    logger.info("=" * 60)
    logger.info(f"8-K MONITOR COMPLETE")
    logger.info(f"  Total 8-K filings scanned: {total_filings}")
    logger.info(f"  Matched to tracked entities: {matched}")
    logger.info(f"  Catalyst filings detected: {catalysts_found}")
    logger.info(f"  Signals created: {signals_created}")
    logger.info("=" * 60)


async def run_loop():
    """Run every 6 hours during weekdays, daily on weekends."""
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_8k_ingestion()
            await report_heartbeat("ingest-8k", duration_seconds=_time.time()-_start, interval_hours=6)
        except Exception as e:
            logger.error(f"8-K ingestion failed: {e}")
            await report_heartbeat("ingest-8k", error=str(e), interval_hours=6)

        now = datetime.utcnow()
        if now.weekday() < 5:  # Weekday
            wait = 6 * 3600
            logger.info("Next 8-K scan in 6 hours")
        else:
            wait = 24 * 3600
            logger.info("Weekend — next 8-K scan in 24 hours")
        await asyncio.sleep(wait)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        asyncio.run(run_8k_ingestion())
    else:
        asyncio.run(run_loop())
