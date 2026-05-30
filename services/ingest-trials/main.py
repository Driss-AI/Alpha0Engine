"""
Clinical Trial Ingestion Worker
=================================
The SPRB gap-filler. Pulls Phase 2/3 clinical trials from
ClinicalTrials.gov, matches them to tracked entities, and creates
signals with real catalyst dates (primary completion dates).

This gives Lens 1 (Binary Catalyst) actual catalyst_proximity_days
instead of estimated/null values.

Pipeline:
  1. Get all tracked biotech/pharma entities
  2. Search CT.gov for each company's active trials
  3. Also bulk-search active Phase 3 trials (catches companies we track)
  4. Match trials to entities
  5. Create signals with:
     - signal_type: "clinical_trial" or "fda_catalyst"
     - raw_data: full trial details + computed catalyst_proximity_days
     - value: bullish signal (0.5-0.9 based on phase/proximity)

Runs daily. ClinicalTrials.gov is free, no API key needed.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal

from ct_client import search_trials, search_by_sponsor
from trial_matcher import match_sponsor_indexed, build_entity_index

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-trials")

# Sectors likely to have clinical trials
BIOTECH_SECTORS = [
    "biotech", "pharma", "pharmaceutical", "healthcare",
    "therapeutics", "bioscience", "oncology", "medical",
    "drug", "clinical", "genomic",
]

CT_RATE_DELAY = 0.5  # Seconds between CT.gov API calls


def _is_biotech_entity(entity: Entity) -> bool:
    """Check if entity is in a biotech/pharma sector."""
    name = (entity.name or "").lower()
    sector = (entity.sector or "").lower()
    combined = name + " " + sector
    return any(kw in combined for kw in BIOTECH_SECTORS)


def _compute_catalyst_proximity(trial: Dict[str, Any]) -> Optional[int]:
    """Compute days until the catalyst (primary completion date)."""
    pcd = trial.get("primary_completion_dt")
    if pcd:
        days = (pcd - datetime.utcnow()).days
        return days

    cd = trial.get("completion_dt")
    if cd:
        days = (cd - datetime.utcnow()).days
        return days

    return None


def _compute_signal_value(trial: Dict[str, Any], proximity_days: Optional[int]) -> float:
    """
    Signal value (0.0-1.0 bullish) based on trial phase and proximity.
    Phase 3 + near completion = highest signal.
    """
    phase = trial.get("phase", "").upper()
    status = trial.get("status", "").upper()

    # Base value by phase
    if "PHASE3" in phase:
        base = 0.75
    elif "PHASE2" in phase:
        base = 0.50
    else:
        base = 0.30

    # Proximity bonus
    if proximity_days is not None:
        if proximity_days <= 30:
            base += 0.15  # Imminent catalyst
        elif proximity_days <= 90:
            base += 0.10
        elif proximity_days <= 180:
            base += 0.05

    # Status bonus
    if status == "COMPLETED":
        base += 0.05  # Results incoming
    elif status == "ACTIVE_NOT_RECRUITING":
        base += 0.03  # Nearing completion

    return min(base, 0.95)


def _classify_catalyst_type(trial: Dict[str, Any]) -> str:
    """Classify the trial into a catalyst type for Lens 1."""
    phase = trial.get("phase", "").upper()
    status = trial.get("status", "").upper()

    if "PHASE3" in phase:
        if status == "COMPLETED":
            return "clinical_trial_data"  # Results pending
        return "fda_pdufa"  # Approaching FDA decision
    if "PHASE2" in phase:
        return "clinical_trial_data"
    return "clinical_trial_data"


async def get_biotech_entities(session: AsyncSession) -> List[Dict[str, Any]]:
    """Get all public entities that might have clinical trials."""
    result = await session.exec(
        select(Entity).where(
            Entity.entity_type == "public",
        ).limit(10000)
    )
    entities = result.all()

    # Include all entities — many biotech companies don't have sector labels
    # The matching will filter out non-matches
    return [
        {
            "id": e.id,
            "name": e.name,
            "ticker": e.ticker,
            "cik": e.cik,
            "sector": e.sector,
            "is_biotech": _is_biotech_entity(e),
        }
        for e in entities
    ]


async def check_existing_signal(
    session: AsyncSession, entity_id: str, nct_id: str,
) -> bool:
    """Check if we already have a signal for this trial."""
    result = await session.exec(
        select(Signal).where(
            Signal.entity_id == entity_id,
            Signal.source_id == nct_id,
        )
    )
    return result.first() is not None


async def run_trial_ingestion():
    """Main daily clinical trial ingestion."""
    logger.info("=" * 60)
    logger.info("CLINICAL TRIAL INGESTION — Starting daily run")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Get all entities
        entities = await get_biotech_entities(session)
        biotech_entities = [e for e in entities if e["is_biotech"]]
        logger.info(f"Total entities: {len(entities)}, biotech-flagged: {len(biotech_entities)}")

        # Build matching index
        entity_index = build_entity_index(entities)

        all_trials = []

        # ── Strategy 1: Search by company name for biotech entities ──
        search_names = set()
        for entity in biotech_entities[:200]:  # Cap to avoid rate limits
            name = entity.get("name", "")
            if name and len(name) > 2:
                search_names.add(name)

        logger.info(f"Searching CT.gov for {len(search_names)} biotech companies...")
        for i, name in enumerate(search_names):
            try:
                trials = await search_by_sponsor(name)
                all_trials.extend(trials)
                if i % 20 == 0 and i > 0:
                    logger.info(f"  Searched {i}/{len(search_names)} companies, {len(all_trials)} trials found...")
                await asyncio.sleep(CT_RATE_DELAY)
            except Exception as e:
                logger.error(f"CT.gov search failed for '{name}': {e}")

        # ── Strategy 2: Bulk search active Phase 3 trials ──
        logger.info("Bulk-searching active Phase 3 trials...")
        try:
            phase3_trials = await search_trials(
                phases=["PHASE3"],
                statuses=["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"],
                page_size=100,
                max_pages=10,
            )
            all_trials.extend(phase3_trials)
            logger.info(f"Got {len(phase3_trials)} Phase 3 trials from bulk search")
        except Exception as e:
            logger.error(f"Phase 3 bulk search failed: {e}")

        # Deduplicate by NCT ID
        seen_ncts = set()
        unique_trials = []
        for trial in all_trials:
            nct = trial.get("nct_id")
            if nct and nct not in seen_ncts:
                seen_ncts.add(nct)
                unique_trials.append(trial)

        logger.info(f"Total unique trials: {len(unique_trials)}")

        # ── Match trials to entities ──
        signals_created = 0
        signals_updated = 0
        unmatched = 0

        for trial in unique_trials:
            sponsor = trial.get("lead_sponsor", "")
            if not sponsor:
                continue

            # Only match industry-sponsored trials (not NIH/academic)
            if trial.get("sponsor_class") not in ("INDUSTRY", ""):
                continue

            # Match sponsor to entity
            matched = match_sponsor_indexed(
                sponsor, entity_index, entities, threshold=0.6,
            )

            if not matched:
                unmatched += 1
                continue

            entity_id = matched["id"]
            nct_id = trial["nct_id"]

            # Check for existing signal
            exists = await check_existing_signal(session, entity_id, nct_id)

            # Compute catalyst data
            proximity_days = _compute_catalyst_proximity(trial)
            signal_value = _compute_signal_value(trial, proximity_days)
            catalyst_type = _classify_catalyst_type(trial)

            raw_data = {
                "nct_id": nct_id,
                "title": trial.get("title"),
                "phase": trial.get("phase"),
                "status": trial.get("status"),
                "lead_sponsor": sponsor,
                "conditions": trial.get("conditions", []),
                "interventions": trial.get("interventions", []),
                "enrollment": trial.get("enrollment"),
                "primary_completion_date": trial.get("primary_completion_date"),
                "completion_date": trial.get("completion_date"),
                "catalyst_proximity_days": proximity_days,
                "catalyst_type": catalyst_type,
                "match_score": matched.get("match_score"),
                "matched_entity_name": matched.get("name"),
                "matched_ticker": matched.get("ticker"),
            }

            signal_date = trial.get("primary_completion_dt") or trial.get("completion_dt") or datetime.utcnow()

            if exists:
                # Update existing signal with fresh data
                result = await session.exec(
                    select(Signal).where(
                        Signal.entity_id == entity_id,
                        Signal.source_id == nct_id,
                    )
                )
                sig = result.first()
                if sig:
                    sig.value = signal_value
                    sig.raw_data = raw_data
                    sig.notes = f"{trial.get('phase', '')} — {trial.get('title', '')[:100]}"
                    session.add(sig)
                    signals_updated += 1
            else:
                # Create new signal
                signal = Signal(
                    entity_id=entity_id,
                    signal_type="clinical_trial",
                    signal_date=signal_date,
                    value=signal_value,
                    raw_data=raw_data,
                    source="clinicaltrials_gov",
                    source_id=nct_id,
                    notes=f"{trial.get('phase', '')} — {trial.get('title', '')[:100]}",
                )
                session.add(signal)
                signals_created += 1

                # Log high-value catalysts
                if signal_value >= 0.7:
                    ticker = matched.get("ticker", "?")
                    logger.info(
                        f"  ★ {ticker} — {trial['phase']} — "
                        f"proximity: {proximity_days}d — "
                        f"value: {signal_value:.2f} — "
                        f"{trial.get('title', '')[:60]}"
                    )

        await session.commit()

        logger.info("=" * 60)
        logger.info(f"CLINICAL TRIAL INGESTION COMPLETE")
        logger.info(f"  Unique trials found: {len(unique_trials)}")
        logger.info(f"  Signals created: {signals_created}")
        logger.info(f"  Signals updated: {signals_updated}")
        logger.info(f"  Unmatched sponsors: {unmatched}")
        logger.info("=" * 60)


async def run_loop():
    """Daily loop."""
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_trial_ingestion()
            await report_heartbeat("ingest-trials", duration_seconds=_time.time()-_start, interval_hours=24)
        except Exception as e:
            logger.error(f"Trial ingestion failed: {e}")
            await report_heartbeat("ingest-trials", error=str(e), interval_hours=24)
        logger.info("Next trial ingestion in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-trials", run_trial_ingestion))
    else:
        asyncio.run(run_loop())
