"""
SEC ingest module — 8-K material events, Form 4 insiders, 13F smart money.
==========================================================================
Merge of the former ingest-8k / ingest-form4 / ingest-13f services
(RESTRUCTURE.md §2): one EDGAR client (`edgar.py`), three parsers
(`filing_classifier`, `form4_parser`, `smart_money`), one scan run.

Scans:
  1. 8-K  — near-real-time catalysts (FDA results, M&A, contracts) + red flags
  2. Form 4 — insider buy/sell clusters for the smart-money lens
  3. 13F  — tracked-fund filings (accumulation signals; infotable wiring TBD)
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx
from sqlmodel import select

from edgar import SEC_BASE, JSON_HEADERS, SEC_DELAY, efts_search, fetch_archive_doc
from filing_classifier import (
    extract_items, classify_catalyst, compute_signal_value, is_catalyst_filing,
    lane_for_catalyst, red_flags_from_classification,
)
import form4_parser
from smart_money import SmartMoneyTracker

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-sec")

FORM4_LOOKBACK_DAYS = 30
FORM4_ENTITY_BATCH = 50

# Funds whose micro-cap accumulation is worth confirming a thesis with.
TRACKED_FUNDS = {
    "TIGER GLOBAL": "tiger_global",
    "COATUE": "coatue",
    "D1 CAPITAL": "d1_capital",
    "ALTIMETER": "altimeter",
    "DRAGONEER": "dragoneer",
    "LONE PINE CAPITAL": "lone_pine",
    "VIKING GLOBAL": "viking",
    "WHALE ROCK CAPITAL": "whale_rock",
    "DURABLE CAPITAL": "durable",
    "STEADFAST CAPITAL": "steadfast",
    "ARK INVEST": "ark_invest",
    "BAILLIE GIFFORD": "baillie_gifford",
    "FIDELITY": "fidelity_crossover",
    "T. ROWE PRICE": "troweprice_crossover",
}


async def _cik_entity_map(session, limit: int = 10000) -> Dict[str, Any]:
    """CIK (unpadded) → public entity."""
    from shared.schemas.entities import Entity
    entities = (await session.exec(
        select(Entity).where(
            Entity.entity_type == "public",
            Entity.cik.isnot(None),  # type: ignore
        ).limit(limit)
    )).all()
    return {e.cik.lstrip("0"): e for e in entities if e.cik}


async def _signal_exists(session, entity_id: str, source_id: str) -> bool:
    from shared.schemas.signals import Signal
    result = await session.exec(
        select(Signal).where(
            Signal.entity_id == entity_id,
            Signal.source_id == source_id,
        )
    )
    return result.first() is not None


# ── Scan 1: 8-K material events ─────────────────────────────────────────────

async def scan_8k(session, client: httpx.AsyncClient, cik_map: Dict[str, Any]) -> int:
    """Scan yesterday+today 8-Ks for tracked entities; write catalyst signals."""
    from shared.schemas.signals import Signal
    from shared.services.catalyst_emitter import upsert_catalyst

    dates = [
        (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"),
        datetime.utcnow().strftime("%Y-%m-%d"),
    ]
    signals_created = 0

    for date_str in dates:
        try:
            hits = await efts_search(client, forms="8-K", startdt=date_str, enddt=date_str)
        except Exception as e:
            logger.error(f"8-K EFTS fetch failed for {date_str}: {e}")
            continue
        logger.info(f"8-K scan {date_str}: {len(hits)} filings")
        await asyncio.sleep(SEC_DELAY)

        for hit in hits:
            src = hit.get("_source", {})
            raw_id = hit.get("_id", "")
            ciks = src.get("ciks", [])
            cik_padded = ciks[0] if isinstance(ciks, list) and ciks else ""
            entity = cik_map.get(cik_padded.lstrip("0"))
            if not entity:
                continue

            accession, _, primary_doc = raw_id.partition(":")
            source_id = f"8k:{accession}"
            if await _signal_exists(session, entity.id, source_id):
                continue

            text = await fetch_archive_doc(client, cik_padded, accession, primary_doc)
            await asyncio.sleep(SEC_DELAY)
            if not text:
                continue
            import re
            text = re.sub(r"<[^>]+>", " ", text[:15000])
            text = re.sub(r"\s+", " ", text).strip()

            items = extract_items(text)
            catalyst = classify_catalyst(text)
            if not is_catalyst_filing(items, catalyst):
                continue

            signal_value = compute_signal_value(items, catalyst)
            cat_type = catalyst.get("catalyst_type") or "8k_event"
            filing_date = src.get("file_date", date_str)
            try:
                sig_date = datetime.fromisoformat(filing_date)
            except (ValueError, TypeError):
                sig_date = datetime.utcnow()

            names = src.get("display_names", [])
            company_name = names[0].split("(CIK")[0].strip() if names and names[0] else ""
            notes = (
                f"8-K Items {','.join(items)} — {cat_type} "
                f"(conf: {catalyst.get('confidence', 0):.0%})"
            )

            session.add(Signal(
                entity_id=entity.id,
                signal_type=cat_type,
                signal_date=sig_date,
                value=signal_value,
                raw_data={
                    "items": items,
                    "catalyst_type": cat_type,
                    "catalyst_confidence": catalyst.get("confidence"),
                    "all_catalysts": catalyst.get("all_matches", {}),
                    "company_name": company_name,
                    "cik": cik_padded.lstrip("0"),
                    "accession": accession,
                    "filing_date": filing_date,
                    "text_preview": text[:500],
                },
                source="edgar_8k",
                source_id=source_id,
                notes=notes[:500],
            ))
            signals_created += 1

            lane = lane_for_catalyst(cat_type)
            if lane and entity.ticker:
                try:
                    await upsert_catalyst(
                        session,
                        ticker=entity.ticker,
                        catalyst_type=lane["catalyst_type"],
                        title=notes[:120],
                        expected_date=sig_date.date(),
                        entity_id=entity.id,
                        status="passed",
                        impact_score=signal_value,
                        details={
                            "lane": lane["lane_id"],
                            "bottleneck": lane["bottleneck"],
                            "source": "8k",
                            "accession": accession,
                        },
                    )
                except Exception as e:
                    logger.error(f"8-K catalyst emit failed: {e}")

            red_flags = red_flags_from_classification(catalyst)
            if red_flags:
                session.add(Signal(
                    entity_id=entity.id,
                    signal_type="red_flag",
                    signal_date=sig_date,
                    value=0.0,
                    raw_data={"red_flags": red_flags, "source": "8k",
                              "accession": accession},
                    source="edgar_8k",
                    source_id=f"{source_id}:redflag",
                    notes=f"8-K red flags: {', '.join(red_flags)}"[:500],
                ))

            if signal_value >= 0.6:
                logger.info(f"  ★ {entity.ticker or '?'} — {cat_type} — value {signal_value:.2f}")

    return signals_created


# ── Scan 2: Form 4 insider transactions ─────────────────────────────────────

async def scan_form4(session, client: httpx.AsyncClient, cik_map: Dict[str, Any]) -> int:
    """Check recent Form 4s for each tracked entity; write insider signals."""
    from shared.schemas.signals import Signal

    entities = list(cik_map.values())
    signals_created = 0
    cutoff = (datetime.utcnow() - timedelta(days=FORM4_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    for batch_start in range(0, len(entities), FORM4_ENTITY_BATCH):
        for entity in entities[batch_start:batch_start + FORM4_ENTITY_BATCH]:
            try:
                url = f"{SEC_BASE}/submissions/CIK{entity.cik.zfill(10)}.json"
                resp = await client.get(url, headers=JSON_HEADERS)
                await asyncio.sleep(SEC_DELAY)
                if resp.status_code != 200:
                    continue
                recent = resp.json().get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                accessions = recent.get("accessionNumber", [])
                primary_docs = recent.get("primaryDocument", [])

                filings = [
                    {"accession": accessions[i], "primary_doc": primary_docs[i],
                     "filing_date": dates[i]}
                    for i in range(len(forms))
                    if forms[i] in ("4", "4/A")
                    and i < len(dates) and dates[i] >= cutoff
                    and i < len(accessions) and accessions[i]
                    and i < len(primary_docs) and primary_docs[i]
                ]

                for filing in filings[:10]:  # Cap per entity
                    source_id = f"form4:{filing['accession']}"
                    if await _signal_exists(session, entity.id, source_id):
                        continue

                    xml = await fetch_archive_doc(
                        client, entity.cik, filing["accession"],
                        filing["primary_doc"], xml=True,
                    )
                    await asyncio.sleep(SEC_DELAY)
                    if not xml:
                        continue

                    parsed = form4_parser.parse_form4_xml(xml)
                    if not parsed or not parsed["transactions"]:
                        continue

                    signal_value = form4_parser.compute_signal_value(parsed)
                    try:
                        sig_date = datetime.fromisoformat(filing["filing_date"])
                    except (ValueError, TypeError):
                        sig_date = datetime.utcnow()

                    tx_summary = []
                    if parsed["buy_count"] > 0:
                        tx_summary.append(
                            f"BUY {parsed['total_buy_shares']:.0f} shares "
                            f"(${parsed['total_buy_value']:,.0f})")
                    if parsed["sell_count"] > 0:
                        tx_summary.append(
                            f"SELL {parsed['total_sell_shares']:.0f} shares "
                            f"(${parsed['total_sell_value']:,.0f})")
                    notes = (
                        f"{parsed['insider_name']} "
                        f"({parsed['insider_title'] or parsed['insider_relationship']}) — "
                        f"{' | '.join(tx_summary)}"
                    )

                    session.add(Signal(
                        entity_id=entity.id,
                        signal_type=form4_parser.insider_signal_type(parsed),
                        signal_date=sig_date,
                        value=signal_value,
                        raw_data={
                            "insider_name": parsed["insider_name"],
                            "insider_title": parsed["insider_title"],
                            "insider_relationship": parsed["insider_relationship"],
                            "transaction_type": "Purchase" if parsed["buy_count"] > 0 else "Sale",
                            "is_open_market_purchase": parsed.get("has_open_market_buy", False),
                            "is_10b5_1": parsed.get("is_10b5_1", False),
                            "shares": parsed["net_shares"],
                            "shares_held": parsed["transactions"][-1].get("shares_after", 0)
                                if parsed["transactions"] else 0,
                            "value_usd": parsed["total_buy_value"] or parsed["total_sell_value"],
                            "transaction_value": parsed["net_value"],
                            "buy_count": parsed["buy_count"],
                            "sell_count": parsed["sell_count"],
                            "issuer_ticker": parsed["issuer_ticker"],
                            "issuer_cik": parsed["issuer_cik"],
                            "filing_date": filing["filing_date"],
                            "accession": filing["accession"],
                        },
                        source="edgar_form4",
                        source_id=source_id,
                        notes=notes[:500],
                    ))
                    signals_created += 1

                    if parsed["buy_count"] > 0 and parsed["total_buy_value"] > 50_000:
                        logger.info(
                            f"  ★ {entity.ticker or parsed['issuer_ticker'] or '?'} — "
                            f"{parsed['insider_name']} BUY ${parsed['total_buy_value']:,.0f}")

            except Exception as e:
                logger.error(f"Form 4 error for {entity.name}: {e}")

        await session.commit()

    return signals_created


# ── Scan 3: 13F tracked funds ───────────────────────────────────────────────

def scan_13f() -> int:
    """Log recent 13F filings from tracked funds (sync — requests-based)."""
    tracker = SmartMoneyTracker(TRACKED_FUNDS)
    filings = tracker.get_recent_13f_filings(days_back=7)
    logger.info(f"13F: {len(filings)} recent filings from tracked funds")
    return len(filings)


# ── Orchestrator ────────────────────────────────────────────────────────────

async def run_sec_ingestion():
    """Run all three SEC scans in sequence."""
    from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables

    logger.info("=" * 60)
    logger.info("SEC INGEST — 8-K + Form 4 + 13F")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        cik_map = await _cik_entity_map(session)
        logger.info(f"Tracking {len(cik_map)} entities by CIK")
        if not cik_map:
            logger.info("No entities with CIKs. Exiting.")
            return

        async with httpx.AsyncClient(timeout=30) as client:
            n_8k = await scan_8k(session, client, cik_map)
            await session.commit()
            n_form4 = await scan_form4(session, client, cik_map)  # commits per batch

    n_13f = await asyncio.to_thread(scan_13f)

    logger.info("=" * 60)
    logger.info(f"SEC INGEST COMPLETE — 8-K signals: {n_8k}, "
                f"Form 4 signals: {n_form4}, 13F filings seen: {n_13f}")
    logger.info("=" * 60)


if __name__ == "__main__":
    if os.environ.get("RUN_MODE", "once") == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-sec", run_sec_ingestion))
    else:
        asyncio.run(run_sec_ingestion())
