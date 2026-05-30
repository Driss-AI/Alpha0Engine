"""
FDA Event Ingestion Worker (Sprint 8.2) — L2 Biotech lane

Pulls recent FDA drug approvals from OpenFDA, matches sponsors to tracked
entities, upserts `fda_events` rows, and emits lane catalysts:
  - approval  -> catalyst_type "fda_approval"
  - crl       -> catalyst_type "crl"        (from 8-K/news, not OpenFDA)
  - pdufa     -> catalyst_type "pdufa_date"  (from 8-K/news)
  - adcom     -> catalyst_type "adcom_date"  (from 8-K/news)

OpenFDA gives the high-confidence "approved" stream. Forward-looking PDUFA/AdCom
catalysts are primarily captured by the 8-K classifier (8.3) + news tagger (8.5)
which write into the same fda_events / catalyst_events tables.

Runs daily. No API key required at low volume.
"""
import os
import sys
import asyncio
import logging
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.fda_event import FDAEvent
from shared.services.catalyst_emitter import upsert_catalyst

from fda_client import fetch_recent_approvals

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-fda")

LOOKBACK_DAYS = int(os.environ.get("FDA_LOOKBACK_DAYS", "30"))

# event_type -> lane catalyst_type
_CATALYST_TYPE = {
    "approval": "fda_approval",
    "crl": "crl",
    "pdufa": "pdufa_date",
    "adcom": "adcom_date",
}


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum() or c.isspace()).strip()


async def _build_company_index(session: AsyncSession) -> dict[str, Entity]:
    """Map normalized company name -> Entity for sponsor matching."""
    entities = (await session.exec(
        select(Entity).where(Entity.entity_type == "public").limit(20000)
    )).all()
    index: dict[str, Entity] = {}
    for e in entities:
        if e.name:
            index[_norm(e.name)] = e
    return index


def _match_sponsor(sponsor: str, index: dict[str, Entity]) -> Entity | None:
    """Match an FDA sponsor name to a tracked entity (exact + substring)."""
    if not sponsor:
        return None
    key = _norm(sponsor)
    if key in index:
        return index[key]
    # Substring: sponsor "ACME PHARMACEUTICALS INC" vs entity "Acme Pharmaceuticals"
    for name_key, ent in index.items():
        if len(name_key) >= 6 and (name_key in key or key in name_key):
            return ent
    return None


async def _upsert_fda_event(session: AsyncSession, ev: dict, entity: Entity | None) -> bool:
    """Upsert one fda_events row. Returns True if newly created."""
    existing = (await session.exec(
        select(FDAEvent).where(
            FDAEvent.event_type == ev["event_type"],
            FDAEvent.drug_name == ev.get("drug_name"),
            FDAEvent.company == ev.get("company"),
            FDAEvent.event_date == ev.get("event_date"),
        )
    )).first()

    if existing:
        if entity and not existing.entity_id:
            existing.entity_id = entity.id
            existing.ticker = entity.ticker
            session.add(existing)
        return False

    session.add(FDAEvent(
        event_type=ev["event_type"],
        drug_name=ev.get("drug_name"),
        company=ev.get("company"),
        ticker=entity.ticker if entity else None,
        entity_id=entity.id if entity else None,
        indication=ev.get("indication"),
        event_date=ev.get("event_date"),
        status=ev.get("status"),
        source_url=ev.get("source_url"),
        raw=ev.get("raw", {}),
    ))
    return True


async def run_fda_ingestion():
    """Daily FDA approvals ingestion."""
    logger.info("=" * 60)
    logger.info("FDA EVENT INGESTION — Starting daily run")
    logger.info("=" * 60)

    await create_db_and_tables()

    since = date.today() - timedelta(days=LOOKBACK_DAYS)
    logger.info(f"Fetching FDA approvals since {since}")
    events = await fetch_recent_approvals(since=since, limit=100)
    logger.info(f"OpenFDA returned {len(events)} approval events")

    created = 0
    matched = 0
    catalysts = 0

    async with AsyncSessionLocal() as session:
        index = await _build_company_index(session)
        logger.info(f"Built sponsor index of {len(index)} entities")

        for ev in events:
            entity = _match_sponsor(ev.get("company", ""), index)
            if entity:
                matched += 1

            try:
                is_new = await _upsert_fda_event(session, ev, entity)
                if is_new:
                    created += 1
            except Exception as e:
                logger.error(f"fda_event upsert failed: {e}")
                continue

            # Emit lane catalyst when we can attribute it to a ticker
            ct_type = _CATALYST_TYPE.get(ev["event_type"])
            if ct_type and entity and entity.ticker:
                try:
                    await upsert_catalyst(
                        session,
                        ticker=entity.ticker,
                        catalyst_type=ct_type,
                        title=f"FDA {ev['event_type']}: {ev.get('drug_name') or 'drug'}",
                        expected_date=ev.get("event_date"),
                        entity_id=entity.id,
                        status="passed" if ev["event_type"] == "approval" else "upcoming",
                        details={"lane": "L2_BIOTECH", "bottleneck": "fda_decision",
                                 "drug_name": ev.get("drug_name")},
                    )
                    catalysts += 1
                except Exception as e:
                    logger.error(f"catalyst emit failed: {e}")

        await session.commit()

    logger.info("=" * 60)
    logger.info(f"FDA INGESTION COMPLETE — {created} new events, "
                f"{matched} matched to entities, {catalysts} catalysts emitted")
    logger.info("=" * 60)
    return {"records_processed": created, "metadata": {"matched": matched, "catalysts": catalysts}}


async def run_loop():
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_fda_ingestion()
            await report_heartbeat("ingest-fda", duration_seconds=_time.time() - _start, interval_hours=24)
        except Exception as e:
            logger.error(f"FDA ingestion failed: {e}")
            await report_heartbeat("ingest-fda", error=str(e), interval_hours=24)
        logger.info("Next FDA ingestion in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-fda", run_fda_ingestion))
    else:
        asyncio.run(run_loop())
