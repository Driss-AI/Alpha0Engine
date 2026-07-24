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
from shared.schemas.clinical_trial import ClinicalTrial
from shared.services.catalyst_emitter import upsert_catalyst

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

CT_RATE_DELAY = 1.0  # Seconds between CT.gov API calls (the endpoint 429s easily)
# A dated readout more than ~2 months in the past is history, not a forward
# catalyst. (Grace window covers "just completed, topline data still pending".)
STALE_TRIAL_DAYS = -60


def _is_biotech_entity(entity: Entity) -> bool:
    """Check if entity is in a biotech/pharma sector."""
    name = (entity.name or "").lower()
    sector = (entity.sector or "").lower()
    combined = name + " " + sector
    return any(kw in combined for kw in BIOTECH_SECTORS)


# Sectors that make a drug-trial match impossible regardless of name. A company
# whose sector is clearly non-medical (metals, autos, banks…) must never get a
# clinical-trial catalyst — this stops exact-abbreviation collisions like
# "ATI" (ATI Inc., specialty metals) or "XOS" (an EV truck maker).
_HEALTH_SECTOR_HINTS = (
    "health", "bio", "pharma", "medic", "therap", "drug", "clinic",
    "genom", "life scien", "diagnost", "oncolog", "vaccine",
)


def _sector_allows_trial(sector: Optional[str]) -> bool:
    """True if the entity's sector is unknown or plausibly medical.

    Unknown sector is allowed (many small biotechs are unlabeled); a sector
    that is present but has no medical hint is rejected.
    """
    if not sector or not sector.strip():
        return True
    s = sector.lower()
    return any(h in s for h in _HEALTH_SECTOR_HINTS)


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


def _trial_catalyst_type(trial: Dict[str, Any], proximity_days: Optional[int]) -> Optional[str]:
    """Map a trial to a lane catalyst type (Sprint 8.1).

    - phase_advance: Phase 2/3 trial that is active/recruiting (pipeline progress)
    - trial_readout: primary completion within 180d (imminent data)
    Returns None when neither applies (too far out / wrong phase).
    """
    phase = (trial.get("phase") or "").upper()
    if proximity_days is not None and proximity_days >= 0 and proximity_days <= 180:
        return "trial_readout"
    if "PHASE3" in phase or "PHASE2" in phase:
        return "phase_advance"
    return None


async def _persist_clinical_trial(
    session: AsyncSession,
    *,
    trial: Dict[str, Any],
    entity_id: str,
    ticker: Optional[str],
    company: Optional[str],
    proximity_days: Optional[int],
) -> None:
    """Upsert a clinical_trials row and emit a lane catalyst when relevant."""
    nct_id = trial["nct_id"]
    conditions = trial.get("conditions") or []
    interventions = trial.get("interventions") or []

    existing = (await session.exec(
        select(ClinicalTrial).where(
            ClinicalTrial.nct_id == nct_id,
            ClinicalTrial.entity_id == entity_id,
        )
    )).first()

    fields = dict(
        nct_id=nct_id,
        entity_id=entity_id,
        ticker=ticker,
        company=company,
        phase=trial.get("phase"),
        status=trial.get("status"),
        condition=", ".join(str(c) for c in conditions[:3]) if conditions else None,
        # interventions from CT.gov v2 are dicts ({name,type,description}); join their names.
        intervention=", ".join(
            i.get("name", "") if isinstance(i, dict) else str(i)
            for i in interventions[:3]
        ).strip(", ") or None if interventions else None,
        primary_completion_date=trial.get("primary_completion_dt"),
        study_completion_date=trial.get("completion_dt"),
        catalyst_proximity_days=proximity_days,
        source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        raw={k: trial.get(k) for k in ("title", "phase", "status", "lead_sponsor", "enrollment")},
    )

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        session.add(existing)
    else:
        session.add(ClinicalTrial(**fields))

    # Emit lane catalyst
    ct_type = _trial_catalyst_type(trial, proximity_days)
    if ct_type and ticker:
        await upsert_catalyst(
            session,
            ticker=ticker,
            catalyst_type=ct_type,
            title=f"{trial.get('phase', 'Trial')} — {(trial.get('title') or '')[:120]}",
            expected_date=trial.get("primary_completion_dt"),
            entity_id=entity_id,
            impact_score=_compute_signal_value(trial, proximity_days),
            details={"nct_id": nct_id, "lane": "L2_BIOTECH", "bottleneck": "clinical_trial"},
        )


async def _upsert_trial_signal(
    session: AsyncSession,
    *,
    nct_id: str,
    entity_id: str,
    signal_value: float,
    raw_data: Dict[str, Any],
    signal_date: datetime,
    notes: str,
) -> str:
    """Create or update the single clinical_trial Signal for an NCT.

    The DB unique key is (source, source_id, signal_type) — entity-agnostic —
    so we look it up that way and update in place (re-pointing entity_id) when
    it exists, rather than inserting a duplicate that would abort the batch.
    Returns "created" or "updated". Relies on autoflush so rows pending from
    earlier in the same run are also found.
    """
    existing = (await session.exec(
        select(Signal).where(
            Signal.source == "clinicaltrials_gov",
            Signal.source_id == nct_id,
            Signal.signal_type == "clinical_trial",
        )
    )).first()
    if existing:
        existing.entity_id = entity_id
        existing.value = signal_value
        existing.raw_data = raw_data
        existing.signal_date = signal_date
        existing.notes = notes
        session.add(existing)
        return "updated"
    session.add(Signal(
        entity_id=entity_id,
        signal_type="clinical_trial",
        signal_date=signal_date,
        value=signal_value,
        raw_data=raw_data,
        source="clinicaltrials_gov",
        source_id=nct_id,
        notes=notes,
    ))
    return "created"


async def _prune_orphan_trial_signals(
    session: AsyncSession, keep_ncts: set,
) -> int:
    """Delete clinical_trial signals not backed by a current match.

    Removes false matches from prior runs (e.g. a biotech trial once glued to
    a truck maker) and now-stale readouts, so old bad data can't keep scoring.
    Guarded by a floor so a failed/empty fetch can't wipe the whole table.
    """
    from sqlalchemy import delete as _delete, func as _func

    total = (await session.exec(
        select(_func.count()).select_from(Signal).where(
            Signal.source == "clinicaltrials_gov",
            Signal.signal_type == "clinical_trial",
        )
    )).one()
    if len(keep_ncts) < 50 or len(keep_ncts) >= total:
        # Too few current matches to trust (likely a bad fetch) — don't prune.
        return 0

    result = await session.exec(
        _delete(Signal).where(
            Signal.source == "clinicaltrials_gov",
            Signal.signal_type == "clinical_trial",
            Signal.source_id.notin_(keep_ncts),  # type: ignore[union-attr]
        )
    )
    await session.commit()
    return result.rowcount or 0


async def _prune_orphan_trial_catalysts(
    session: AsyncSession, keep_ncts: set,
) -> int:
    """Delete trial-derived catalyst_events not backed by a current match.

    Companion to the signal prune: clears the CALENDAR of false/stale trial
    catalysts (e.g. an FDA date wrongly pinned to a truck maker). Only touches
    clinical-trial-sourced, non-user-pinned events; never FDA/8-K/news or
    anything the user pinned. Same floor guard against a bad fetch.
    """
    from shared.schemas.catalyst_event import CatalystEvent

    if len(keep_ncts) < 50:
        return 0

    rows = (await session.exec(
        select(CatalystEvent).where(
            CatalystEvent.catalyst_type.in_(("trial_readout", "phase_advance")),  # type: ignore[union-attr]
            CatalystEvent.user_pinned == False,  # noqa: E712
        )
    )).all()

    removed = 0
    for row in rows:
        details = row.details or {}
        if details.get("bottleneck") != "clinical_trial":
            continue  # not trial-sourced — leave it alone
        nct = details.get("nct_id")
        if not nct or nct not in keep_ncts:
            await session.delete(row)
            removed += 1
    if removed:
        await session.commit()
    return removed


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

        # ── Strategy 2: Bulk search active Phase 2/3 trials ──
        # The efficient path: a few paginated requests cover most industry
        # Phase 2/3 trials, which we then match to entities by sponsor.
        logger.info("Bulk-searching active Phase 2/3 trials...")
        try:
            bulk_trials = await search_trials(
                phases=["PHASE2", "PHASE3"],
                statuses=["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"],
                page_size=100,
                max_pages=20,
            )
            all_trials.extend(bulk_trials)
            logger.info(f"Got {len(bulk_trials)} Phase 2/3 trials from bulk search")
        except Exception as e:
            logger.error(f"Bulk Phase 2/3 search failed: {e}")

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
        skipped_dupes = 0
        stale_skipped = 0
        wrong_sector = 0
        # NCTs that hold a valid, current clinical_trial signal after this run.
        # Anything else in the table is an orphan from a prior run (a false
        # match that no longer resolves, or a now-stale readout) and gets
        # deleted at the end so old bad data can't linger in the scores.
        persisted_ncts: set[str] = set()
        # A clinical_trial Signal is unique on (source, source_id, signal_type)
        # in the DB — NOT on entity_id. Two entities can fuzzy-match the same
        # trial sponsor, so track which NCTs we've already handled this run and
        # look up existing rows by the real DB key to avoid duplicate-key aborts.
        seen_ncts_this_run: set[str] = set()

        async def _flush(tag: str) -> None:
            """Commit accumulated signals; roll back (not crash) on any error."""
            try:
                await session.commit()
            except Exception as e:
                logger.error(f"trial signal commit failed ({tag}), rolling back: {e}")
                await session.rollback()

        for idx, trial in enumerate(unique_trials):
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

            # Reject the match if the company's sector is clearly non-medical —
            # a metals or auto company can't own a drug trial no matter how its
            # name collides with the sponsor.
            if not _sector_allows_trial(matched.get("sector")):
                wrong_sector += 1
                continue

            entity_id = matched["id"]
            nct_id = trial["nct_id"]

            # One signal per trial per run (the DB key ignores entity_id).
            if nct_id in seen_ncts_this_run:
                skipped_dupes += 1
                continue
            seen_ncts_this_run.add(nct_id)

            # Compute catalyst data
            proximity_days = _compute_catalyst_proximity(trial)
            # A trial whose readout already happened (well in the past) is NOT a
            # forward catalyst. Skip stale completions so a 2006 Phase 3 at
            # -7000 days can't masquerade as an upcoming "big event". Undated
            # trials (proximity None) are kept as pipeline-progress signals.
            if proximity_days is not None and proximity_days < STALE_TRIAL_DAYS:
                stale_skipped += 1
                continue
            signal_value = _compute_signal_value(trial, proximity_days)
            catalyst_type = _classify_catalyst_type(trial)

            # Sprint 8.1: persist a clinical_trials row + emit lane catalyst
            try:
                await _persist_clinical_trial(
                    session,
                    trial=trial,
                    entity_id=entity_id,
                    ticker=matched.get("ticker"),
                    company=matched.get("name"),
                    proximity_days=proximity_days,
                )
            except Exception as e:
                logger.error(f"clinical_trials persist failed for {nct_id}: {e}")

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
            notes = f"{trial.get('phase', '')} — {trial.get('title', '')[:100]}"

            outcome = await _upsert_trial_signal(
                session, nct_id=nct_id, entity_id=entity_id, signal_value=signal_value,
                raw_data=raw_data, signal_date=signal_date, notes=notes,
            )
            persisted_ncts.add(nct_id)
            if outcome == "updated":
                signals_updated += 1
            else:
                signals_created += 1
                if signal_value >= 0.7:
                    ticker = matched.get("ticker", "?")
                    logger.info(
                        f"  ★ {ticker} — {trial['phase']} — "
                        f"proximity: {proximity_days}d — "
                        f"value: {signal_value:.2f} — "
                        f"{trial.get('title', '')[:60]}"
                    )

            # Commit in batches so one bad row can't discard the whole run's work.
            if (idx + 1) % 100 == 0:
                await _flush(f"batch@{idx + 1}")

        await _flush("final")

        orphans_removed = await _prune_orphan_trial_signals(session, persisted_ncts)
        orphan_catalysts = await _prune_orphan_trial_catalysts(session, persisted_ncts)

        logger.info("=" * 60)
        logger.info(f"CLINICAL TRIAL INGESTION COMPLETE")
        logger.info(f"  Unique trials found: {len(unique_trials)}")
        logger.info(f"  Signals created: {signals_created}")
        logger.info(f"  Signals updated: {signals_updated}")
        logger.info(f"  Duplicate trials skipped: {skipped_dupes}")
        logger.info(f"  Stale (past-readout) trials skipped: {stale_skipped}")
        logger.info(f"  Non-medical sector rejected: {wrong_sector}")
        logger.info(f"  Unmatched sponsors: {unmatched}")
        logger.info(f"  Orphan signals pruned: {orphans_removed}")
        logger.info(f"  Orphan calendar catalysts pruned: {orphan_catalysts}")
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
