"""
Fundamental Screener — Main Worker
===================================
Module 3 worker. Runs on a schedule (daily) or on-demand via Redis trigger.
Iterates over all entities, computes moat + financial scores,
stores results in fundamental_scores table.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.signals import Signal
from shared.schemas.fundamentals import FundamentalScore

from moat_scorer import compute_moat_score
from public_screener import screen_public_equity
from private_proxy import screen_private_company
from scoring_engine import compute_fundamental_score

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s | %(name)s | %(message)s")
logger = logging.getLogger("fundamental-screener")

BATCH_SIZE = 50


async def get_entity_signals(session: AsyncSession, entity_id: str) -> list:
    """Fetch all signals for an entity."""
    result = await session.exec(
        select(Signal).where(Signal.entity_id == entity_id)
    )
    signals = result.all()
    return [
        {
            "signal_type": s.signal_type,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
            "value": s.value,
            "source": s.source,
            "notes": s.notes,
            "raw_data": s.raw_data or {},
        }
        for s in signals
    ]


async def get_sector_avg_signals(session: AsyncSession, sector: str) -> float:
    """Get average signal count for entities in the same sector."""
    entities = (await session.exec(
        select(Entity).where(Entity.sector == sector)
    )).all()
    if not entities:
        return 10.0  # Default

    total_signals = 0
    for e in entities[:100]:  # Cap for performance
        count = len((await session.exec(
            select(Signal).where(Signal.entity_id == e.id).limit(500)
        )).all())
        total_signals += count

    return max(total_signals / max(len(entities), 1), 1.0)


async def score_entity(session: AsyncSession, entity: Entity, sector_avg: float) -> FundamentalScore:
    """Score a single entity — moat + financials → composite."""
    signals = await get_entity_signals(session, entity.id)
    logger.info(f"Scoring {entity.name} ({entity.entity_type}) — {len(signals)} signals")

    # ── Step 1: Moat Score ──────────────────────────────────
    moat = compute_moat_score(signals, sector_avg_signals=sector_avg)

    # ── Step 2: Financial Metrics ───────────────────────────
    public_metrics = None
    private_metrics = None

    if entity.entity_type == "public" and entity.cik:
        public_metrics = await screen_public_equity(entity.cik)
    else:
        private_metrics = screen_private_company(signals)

    # ── Step 3: Composite Score ─────────────────────────────
    composite = compute_fundamental_score(
        moat=moat,
        public_metrics=public_metrics,
        private_metrics=private_metrics,
        entity_type=entity.entity_type or "private",
    )

    # ── Step 4: Build FundamentalScore record ───────────────
    now = datetime.utcnow()

    # Check for existing score to update
    existing = (await session.exec(
        select(FundamentalScore).where(FundamentalScore.entity_id == entity.id)
    )).first()

    if existing:
        existing.patent_strength = moat["patent_strength"]
        existing.ip_breadth = moat["ip_breadth"]
        existing.talent_density = moat["talent_density"]
        existing.github_momentum = moat["github_momentum"]
        existing.competitive_position = moat["competitive_position"]
        existing.moat_score = moat["moat_score"]
        existing.fundamental_score = composite["fundamental_score"]
        existing.screening_tier = composite["screening_tier"]
        existing.screening_notes = composite.get("screening_notes")
        existing.updated_at = now
        existing.raw_metrics = {
            "moat_pillars": moat,
            "components": composite.get("components", {}),
            "weights": composite.get("weights", {}),
        }

        # Update public/private fields
        if public_metrics and "error" not in public_metrics:
            existing.market_cap_usd = public_metrics.get("market_cap_usd")
            existing.gross_margin = public_metrics.get("gross_margin")
            existing.gross_margin_velocity = public_metrics.get("gross_margin_velocity")
            existing.revenue_growth_yoy = public_metrics.get("revenue_growth_yoy")
            existing.cash_runway_months = public_metrics.get("cash_runway_months")
            existing.rule_of_40 = public_metrics.get("rule_of_40")
            if public_metrics.get("rd_expense") and public_metrics.get("market_cap_usd"):
                existing.rd_to_mktcap = public_metrics["rd_expense"] / public_metrics["market_cap_usd"]

        if private_metrics:
            existing.last_round_valuation = private_metrics.get("last_round_valuation")
            existing.secondary_vs_primary = private_metrics.get("secondary_vs_primary")
            existing.estimated_burn_rate = private_metrics.get("estimated_burn_rate")
            existing.estimated_runway_months = private_metrics.get("estimated_runway_months")
            existing.total_raised = private_metrics.get("total_raised")
            existing.form_d_total = private_metrics.get("form_d_count")

        session.add(existing)
        return existing

    # Create new
    score_record = FundamentalScore(
        entity_id=entity.id,
        patent_strength=moat["patent_strength"],
        ip_breadth=moat["ip_breadth"],
        talent_density=moat["talent_density"],
        github_momentum=moat["github_momentum"],
        competitive_position=moat["competitive_position"],
        moat_score=moat["moat_score"],
        fundamental_score=composite["fundamental_score"],
        screening_tier=composite["screening_tier"],
        screening_notes=composite.get("screening_notes"),
        scored_at=now,
        updated_at=now,
        raw_metrics={
            "moat_pillars": moat,
            "components": composite.get("components", {}),
            "weights": composite.get("weights", {}),
        },
    )

    if public_metrics and "error" not in public_metrics:
        score_record.market_cap_usd = public_metrics.get("market_cap_usd")
        score_record.gross_margin = public_metrics.get("gross_margin")
        score_record.gross_margin_velocity = public_metrics.get("gross_margin_velocity")
        score_record.revenue_growth_yoy = public_metrics.get("revenue_growth_yoy")
        score_record.cash_runway_months = public_metrics.get("cash_runway_months")
        score_record.rule_of_40 = public_metrics.get("rule_of_40")
        if public_metrics.get("rd_expense") and public_metrics.get("market_cap_usd"):
            score_record.rd_to_mktcap = public_metrics["rd_expense"] / public_metrics["market_cap_usd"]

    if private_metrics:
        score_record.last_round_valuation = private_metrics.get("last_round_valuation")
        score_record.secondary_vs_primary = private_metrics.get("secondary_vs_primary")
        score_record.estimated_burn_rate = private_metrics.get("estimated_burn_rate")
        score_record.estimated_runway_months = private_metrics.get("estimated_runway_months")
        score_record.total_raised = private_metrics.get("total_raised")
        score_record.form_d_total = private_metrics.get("form_d_count")

    session.add(score_record)
    return score_record


async def run_screening_batch():
    """Run the full fundamental screening across all entities."""
    logger.info("=" * 60)
    logger.info("FUNDAMENTAL SCREENING — Starting batch run")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        entities = (await session.exec(select(Entity).limit(1000))).all()
        logger.info(f"Found {len(entities)} entities to screen")

        if not entities:
            logger.info("No entities to screen. Exiting.")
            return

        # Pre-compute sector averages
        sectors = set(e.sector for e in entities if e.sector)
        sector_avgs = {}
        for sector in sectors:
            sector_avgs[sector] = await get_sector_avg_signals(session, sector)

        scored = 0
        errors = 0
        tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0, "unscored": 0}

        for i in range(0, len(entities), BATCH_SIZE):
            batch = entities[i:i + BATCH_SIZE]
            for entity in batch:
                try:
                    sector_avg = sector_avgs.get(entity.sector, 10.0)
                    result = await score_entity(session, entity, sector_avg)
                    tier_counts[result.screening_tier] = tier_counts.get(result.screening_tier, 0) + 1
                    scored += 1
                except Exception as e:
                    logger.error(f"Error scoring {entity.name}: {e}")
                    errors += 1

            await session.commit()
            logger.info(f"Committed batch {i // BATCH_SIZE + 1} ({scored} scored, {errors} errors)")

            # Rate-limit SEC API calls
            await asyncio.sleep(0.5)

    logger.info("=" * 60)
    logger.info(f"SCREENING COMPLETE — {scored} scored, {errors} errors")
    logger.info(f"Tier breakdown: {tier_counts}")
    logger.info("=" * 60)


async def run_loop():
    """Run screening on a daily loop."""
    while True:
        try:
            await run_screening_batch()
        except Exception as e:
            logger.error(f"Screening batch failed: {e}")
        # Sleep 24 hours
        logger.info("Next screening run in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        asyncio.run(run_screening_batch())
    else:
        asyncio.run(run_loop())
