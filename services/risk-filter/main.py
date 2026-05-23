"""
Risk Filter — Main Worker
==========================
Module 4 worker. Runs daily after fundamental-screener.
Assesses hype, illiquidity, and composite risk for all entities.
"""
import os, sys, asyncio, logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal
from shared.schemas.risk import RiskAssessment

from hype_detector import detect_hype_patterns
from illiquidity_scorer import compute_illiquidity_risk
from risk_engine import compute_risk_score

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s | %(name)s | %(message)s")
logger = logging.getLogger("risk-filter")

BATCH_SIZE = 50


async def get_entity_signals(session: AsyncSession, entity_id: str) -> list:
    result = await session.exec(select(Signal).where(Signal.entity_id == entity_id))
    return [
        {"signal_type": s.signal_type, "signal_date": s.signal_date.isoformat() if s.signal_date else None,
         "value": s.value, "source": s.source, "notes": s.notes, "raw_data": s.raw_data or {}}
        for s in result.all()
    ]


async def get_sector_stats(session: AsyncSession, sector: str) -> dict:
    entities = (await session.exec(select(Entity).where(Entity.sector == sector))).all()
    if not entities:
        return {"avg_signals": 10.0, "entity_count": 1}
    total = 0
    for e in entities[:100]:
        count = len((await session.exec(select(Signal).where(Signal.entity_id == e.id).limit(500))).all())
        total += count
    return {"avg_signals": max(total / len(entities), 1.0), "entity_count": len(entities)}


async def assess_entity(session: AsyncSession, entity: Entity, sector_stats: dict) -> RiskAssessment:
    signals = await get_entity_signals(session, entity.id)
    logger.info(f"Assessing risk: {entity.name} ({entity.entity_type}) — {len(signals)} signals")

    # Step 1: Hype detection
    hype_result = detect_hype_patterns(signals)

    # Step 2: Illiquidity risk (get runway from fundamental_scores if available)
    estimated_runway = None
    try:
        from shared.schemas.fundamentals import FundamentalScore
        fs = (await session.exec(
            select(FundamentalScore).where(FundamentalScore.entity_id == entity.id)
        )).first()
        if fs:
            estimated_runway = fs.estimated_runway_months or fs.cash_runway_months
    except Exception:
        pass

    illiquidity_result = compute_illiquidity_risk(signals, estimated_runway=estimated_runway)

    # Step 3: Composite risk
    risk_result = compute_risk_score(
        hype_result=hype_result,
        illiquidity_result=illiquidity_result,
        entity_signal_count=len(signals),
        sector_avg_signals=sector_stats["avg_signals"],
        sector_entity_count=sector_stats["entity_count"],
    )

    now = datetime.utcnow()

    # Upsert
    existing = (await session.exec(
        select(RiskAssessment).where(RiskAssessment.entity_id == entity.id)
    )).first()

    data = {
        "hype_score": hype_result["hype_score"],
        "substance_score": hype_result["substance_score"],
        "hype_gap": hype_result["hype_gap"],
        "hype_flag": hype_result["hype_flag"],
        "illiquidity_score": illiquidity_result["illiquidity_score"],
        "runway_risk": illiquidity_result["runway_risk"],
        "funding_stale_months": illiquidity_result["funding_stale_months"],
        "market_freeze_exposure": illiquidity_result["market_freeze_exposure"],
        "illiquidity_flag": illiquidity_result["illiquidity_flag"],
        "signal_concentration": illiquidity_result["signal_concentration"],
        "sector_crowding": risk_result["components"]["sector_crowding"],
        "risk_score": risk_result["risk_score"],
        "risk_tier": risk_result["risk_tier"],
        "risk_flags": risk_result["risk_flags"],
        "risk_notes": risk_result["risk_notes"],
        "raw_risk_data": {"hype": hype_result, "illiquidity": illiquidity_result, "composite": risk_result},
        "updated_at": now,
    }

    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        session.add(existing)
        return existing

    record = RiskAssessment(entity_id=entity.id, assessed_at=now, **data)
    session.add(record)
    return record


async def run_risk_batch():
    logger.info("=" * 60)
    logger.info("RISK FILTERING — Starting batch run")
    logger.info("=" * 60)
    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        entities = (await session.exec(select(Entity).limit(1000))).all()
        logger.info(f"Found {len(entities)} entities to assess")
        if not entities:
            return

        sectors = set(e.sector for e in entities if e.sector)
        sector_cache = {}
        for sector in sectors:
            sector_cache[sector] = await get_sector_stats(session, sector)

        assessed = 0
        errors = 0
        tier_counts = {"GREEN": 0, "YELLOW": 0, "ORANGE": 0, "RED": 0}

        for i in range(0, len(entities), BATCH_SIZE):
            batch = entities[i:i + BATCH_SIZE]
            for entity in batch:
                try:
                    stats = sector_cache.get(entity.sector, {"avg_signals": 10.0, "entity_count": 5})
                    result = await assess_entity(session, entity, stats)
                    tier_counts[result.risk_tier] = tier_counts.get(result.risk_tier, 0) + 1
                    assessed += 1
                except Exception as e:
                    logger.error(f"Error assessing {entity.name}: {e}")
                    errors += 1
            await session.commit()
            logger.info(f"Batch {i // BATCH_SIZE + 1} done ({assessed} assessed, {errors} errors)")

    logger.info(f"RISK ASSESSMENT COMPLETE — {assessed} assessed, {errors} errors")
    logger.info(f"Tier breakdown: {tier_counts}")


async def run_loop():
    while True:
        try:
            await run_risk_batch()
        except Exception as e:
            logger.error(f"Risk batch failed: {e}")
        logger.info("Next risk assessment in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        asyncio.run(run_risk_batch())
    else:
        asyncio.run(run_loop())
