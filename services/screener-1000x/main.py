"""
1000x Screener — Main Worker
==============================
Module 5 worker. Runs daily or on-demand.
Iterates over all public entities, scores them across 5 lenses,
stores results in equity_screens table.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone
from typing import Optional

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
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.market_context import MarketContextSignal

from lens_binary_catalyst import score_binary_catalyst
from lens_earnings_inflection import score_earnings_inflection
from lens_demand_rider import score_demand_rider
from lens_float_mechanics import score_float_mechanics
from lens_smart_money import score_smart_money
from composite_engine import compute_1000x_score
from lane_assignment import assign_lanes
from shared.lanes import get_lane
from shared.scoring import compute_axes, classify_bucket, detect_red_flags
from shared.services.evidence_recorder import record_evidence
from shared.services.snapshots import write_daily_snapshots

from shared.logging import setup_logging, get_logger

setup_logging("screener-1000x")
logger = get_logger("screener-1000x")

BATCH_SIZE = 25
SEC_RATE_LIMIT_DELAY = 0.2  # SEC allows 10 req/sec


async def get_entity_signals(session: AsyncSession, entity_id: str) -> list:
    """Fetch all signals for an entity."""
    result = await session.exec(
        select(Signal).where(Signal.entity_id == entity_id)
    )
    return [
        {
            "signal_id": s.id,
            "signal_type": s.signal_type,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
            "value": s.value,
            "source": s.source,
            "notes": s.notes,
            "raw_data": s.raw_data or {},
        }
        for s in result.all()
    ]


async def load_active_market_context(session: AsyncSession) -> list[dict]:
    """Load active market-wide context signals (S11.3).

    Read once per batch and passed into the demand-rider lens so a macro signal
    (e.g. hyperscaler capex inflection) reaches the score for every candidate.
    """
    rows = (await session.exec(
        select(MarketContextSignal).where(MarketContextSignal.is_active == True)  # noqa: E712
    )).all()
    return [
        {
            "context_type": r.context_type,
            "lane_id": r.lane_id,
            "value": r.value,
            "period": r.period,
            "is_active": r.is_active,
        }
        for r in rows
    ]


async def get_fundamental_data(session: AsyncSession, entity_id: str) -> dict:
    """Get existing fundamental score data for the entity."""
    result = await session.exec(
        select(FundamentalScore).where(FundamentalScore.entity_id == entity_id)
    )
    fs = result.first()
    if not fs:
        return {}
    return {
        "market_cap_usd": fs.market_cap_usd,
        "cash_runway_months": fs.cash_runway_months,
        "revenue_growth_yoy": fs.revenue_growth_yoy,
        "gross_margin": fs.gross_margin,
        "moat_score": fs.moat_score,
    }


async def score_entity(
    session: AsyncSession,
    entity: Entity,
    market_context: Optional[list] = None,
) -> EquityScreen:
    """Score a single public entity across all 5 lenses."""
    signals = await get_entity_signals(session, entity.id)
    fundamentals = await get_fundamental_data(session, entity.id)

    market_cap = fundamentals.get("market_cap_usd")
    cash_runway = fundamentals.get("cash_runway_months")

    logger.info(f"Scoring {entity.name} (CIK={entity.cik}, ticker={entity.ticker}) — {len(signals)} signals")

    # ── Lens 1: Binary Catalyst ─────────────────────────────
    try:
        lens1 = score_binary_catalyst(
            market_cap=market_cap,
            cash_runway_months=cash_runway,
            signals=signals,
        )
    except Exception as e:
        logger.error(f"Lens 1 error for {entity.name}: {e}")
        lens1 = {"catalyst_score": 0.0, "catalyst_type": None,
                 "catalyst_proximity_days": None, "catalyst_details": {"error": str(e)}}

    # ── Lens 2: Earnings Inflection ─────────────────────────
    try:
        lens2 = await score_earnings_inflection(cik=entity.cik or "")
        await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
    except Exception as e:
        logger.error(f"Lens 2 error for {entity.name}: {e}")
        lens2 = {"earnings_score": 0.0, "eps_trajectory": "error",
                 "quarters_to_profit": None, "revenue_acceleration": None,
                 "margin_expansion_rate": None, "earnings_details": {"error": str(e)}}

    # ── Lens 3: Structural Demand Rider ─────────────────────
    try:
        lens3 = score_demand_rider(
            signals=signals,
            entity_type=entity.entity_type or "public",
            sector=entity.sector,
            market_cap=market_cap,
            market_context=market_context,
        )
    except Exception as e:
        logger.error(f"Lens 3 error for {entity.name}: {e}")
        lens3 = {"demand_score": 0.0, "megatrend_alignment": None,
                 "theme_strength": None, "institutional_neglect": None,
                 "demand_details": {"error": str(e)}}

    # ── Lens 4: Float Mechanics ─────────────────────────────
    try:
        lens4 = await score_float_mechanics(
            ticker=entity.ticker,
            cik=entity.cik,
            signals=signals,
        )
        await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
    except Exception as e:
        logger.error(f"Lens 4 error for {entity.name}: {e}")
        lens4 = {"float_score": 0.0, "float_category": "unknown",
                 "squeeze_potential": None, "days_to_cover": None,
                 "float_details": {"error": str(e)}}

    # ── Lens 5: Smart Money ─────────────────────────────────
    try:
        lens5 = score_smart_money(
            signals=signals,
            market_cap=market_cap,
            cik=entity.cik,
        )
    except Exception as e:
        logger.error(f"Lens 5 error for {entity.name}: {e}")
        lens5 = {"smart_money_score": 0.0, "institutional_buys_13f": 0,
                 "insider_buys_form4": 0, "insider_buy_value_usd": 0,
                 "smart_money_details": {"error": str(e)}}

    # ── Lane assignment (Sprint 7.3) ────────────────────────
    # Assign the entity to zero or more theme lanes based on its filings/signals.
    try:
        assigned = await assign_lanes(session, entity, signals, market_cap)
    except Exception as e:
        logger.error(f"Lane assignment error for {entity.name}: {e}")
        assigned = []

    raw_lens_scores = dict(
        catalyst_score=lens1["catalyst_score"],
        earnings_score=lens2["earnings_score"],
        demand_score=lens3["demand_score"],
        float_score=lens4["float_score"],
        smart_money_score=lens5["smart_money_score"],
    )

    # ── Composite Score, per lane (Sprint 7.4) ──────────────
    # Score once per matched lane using that lane's weights; the headline
    # composite is the best-scoring lane. Falls back to global weights when the
    # entity matches no lane (preserves pre-Sprint-7 behavior).
    per_lane_composites: dict[str, dict] = {}
    for cl in assigned:
        try:
            lane = get_lane(cl.lane_id)
        except KeyError:
            continue
        per_lane_composites[cl.lane_id] = compute_1000x_score(
            **raw_lens_scores,
            weights=lane.scoring_weights,
            lane_id=cl.lane_id,
        )

    if per_lane_composites:
        best_lane_id = max(
            per_lane_composites,
            key=lambda lid: per_lane_composites[lid]["composite_score"],
        )
        composite = per_lane_composites[best_lane_id]
    else:
        composite = compute_1000x_score(**raw_lens_scores)
        best_lane_id = None

    # ── Sprint 9: red flags → multi-axis → bucket → evidence ────────────────
    catalyst_proximity = lens1.get("catalyst_proximity_days")
    volume_ratio = None
    for s in signals:
        if s.get("signal_type") in ("volume_awakening", "price_breakout"):
            volume_ratio = (s.get("raw_data") or {}).get("volume_ratio") or volume_ratio
    institutional = any(
        s.get("signal_type") in ("institutional_accumulation", "sec_13f", "crossover_filing")
        for s in signals
    )

    red = detect_red_flags(
        lane_id=best_lane_id,
        signals=signals,
        market_cap_usd=market_cap,
        volume_ratio=volume_ratio,
        has_catalyst_date=catalyst_proximity is not None,
    )

    # Record evidence first so confidence can count it.
    try:
        evidence_count = await record_evidence(
            session,
            entity_id=entity.id,
            ticker=entity.ticker,
            lane_id=best_lane_id,
            signals=signals,
        )
    except Exception as e:
        logger.error(f"evidence recording failed for {entity.name}: {e}")
        evidence_count = 0

    axes = compute_axes(
        composite_score=composite["composite_score"],
        active_lenses=composite["active_lenses"],
        market_cap_usd=market_cap,
        cash_runway_months=cash_runway,
        short_pct_float=lens4.get("short_pct_float"),
        float_shares=lens4.get("float_shares"),
        days_to_cover=lens4.get("days_to_cover"),
        volume_ratio=volume_ratio,
        catalyst_proximity_days=catalyst_proximity,
        evidence_count=evidence_count,
        institutional_confirmation=institutional,
        red_flag_count=len(red["red_flags"]),
        has_critical_flag=red["has_critical"],
    )
    lane_live_validated = True
    if best_lane_id:
        try:
            lane_live_validated = get_lane(best_lane_id).is_live_validated()
        except KeyError:
            lane_live_validated = True
    bucket = classify_bucket(
        axes,
        has_critical_flag=red["has_critical"],
        has_dated_catalyst=catalyst_proximity is not None,
        lane_live_validated=lane_live_validated,
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Check for existing record
    existing = (await session.exec(
        select(EquityScreen).where(EquityScreen.entity_id == entity.id)
    )).first()

    record_data = {
        "entity_id": entity.id,
        "ticker": entity.ticker,
        "company_name": entity.name,
        "cik": entity.cik,
        "market_cap_usd": market_cap,
        "shares_outstanding": lens4.get("float_details", {}).get("shares_outstanding"),
        "float_shares": lens4.get("float_shares"),
        "short_interest": lens4.get("short_interest"),
        "short_pct_float": lens4.get("short_pct_float"),
        # Lens 1
        "catalyst_score": lens1["catalyst_score"],
        "catalyst_type": lens1.get("catalyst_type"),
        "catalyst_proximity_days": lens1.get("catalyst_proximity_days"),
        "catalyst_details": lens1.get("catalyst_details", {}),
        # Lens 2
        "earnings_score": lens2["earnings_score"],
        "eps_trajectory": lens2.get("eps_trajectory"),
        "quarters_to_profit": lens2.get("quarters_to_profit"),
        "revenue_acceleration": lens2.get("revenue_acceleration"),
        "margin_expansion_rate": lens2.get("margin_expansion_rate"),
        "earnings_details": lens2.get("earnings_details", {}),
        # Lens 3
        "demand_score": lens3["demand_score"],
        "megatrend_alignment": lens3.get("megatrend_alignment"),
        "theme_strength": lens3.get("theme_strength"),
        "institutional_neglect": lens3.get("institutional_neglect"),
        "demand_details": lens3.get("demand_details", {}),
        # Lens 4
        "float_score": lens4["float_score"],
        "float_category": lens4.get("float_category"),
        "squeeze_potential": lens4.get("squeeze_potential"),
        "days_to_cover": lens4.get("days_to_cover"),
        "float_details": lens4.get("float_details", {}),
        # Lens 5
        "smart_money_score": lens5["smart_money_score"],
        "institutional_buys_13f": lens5.get("institutional_buys_13f"),
        "insider_buys_form4": lens5.get("insider_buys_form4"),
        "insider_buy_value_usd": lens5.get("insider_buy_value_usd"),
        "smart_money_details": lens5.get("smart_money_details", {}),
        # Composite
        "composite_score": composite["composite_score"],
        "conviction_tier": composite["conviction_tier"],
        "active_lenses": composite["active_lenses"],
        "top_lens": composite.get("top_lens"),
        "screening_notes": composite.get("screening_notes"),
        "on_watchlist": composite["conviction_tier"] in ("CONVICTION", "HIGH"),
        # Sprint 9: multi-axis + bucket
        "best_lane_id": best_lane_id,
        "opportunity_score": axes.opportunity,
        "risk_score": axes.risk,
        "timing_score": axes.timing,
        "confidence_score": axes.confidence,
        "tradability_score": axes.tradability,
        "bucket": bucket,
        "raw_data": {
            "composite_details": composite,
            "fundamentals_used": fundamentals,
            # Sprint 9: axes + red flags
            "axes": axes.to_dict(),
            "bucket": bucket,
            "red_flags": red["red_flags"],
            "critical_flags": red["critical_flags"],
            # Sprint 7: lane context
            "best_lane_id": best_lane_id,
            "lanes": [
                {
                    "lane_id": cl.lane_id,
                    "lane_score": cl.lane_score,
                    "bottleneck_exposure": cl.bottleneck_exposure,
                    "composite_score": per_lane_composites.get(cl.lane_id, {}).get("composite_score"),
                    "conviction_tier": per_lane_composites.get(cl.lane_id, {}).get("conviction_tier"),
                }
                for cl in assigned
            ],
            "citation_chain": {
                "binary_catalyst": lens1.get("cited_signal_ids", []),
                "demand_rider": lens3.get("cited_signal_ids", []),
                "float_mechanics": lens4.get("cited_signal_ids", []),
                "smart_money": lens5.get("cited_signal_ids", []),
            },
        },
    }

    if existing:
        for key, val in record_data.items():
            setattr(existing, key, val)
        existing.updated_at = now
        session.add(existing)
        return existing
    else:
        record = EquityScreen(**record_data, screened_at=now, updated_at=now)
        session.add(record)
        return record


async def run_screening_batch():
    """Run the 1000x screener across all public entities."""
    logger.info("=" * 60)
    logger.info("1000x SCREENER — Starting batch run")
    logger.info("=" * 60)

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Only screen public entities with CIK numbers
        entities = (await session.exec(
            select(Entity).where(
                Entity.entity_type == "public",
                Entity.cik.isnot(None),  # type: ignore[union-attr]
            ).limit(2000)
        )).all()
        logger.info(f"Found {len(entities)} public entities to screen")

        if not entities:
            logger.info("No public entities found. Exiting.")
            return

        # S11.3: load active market-wide context once; feeds the demand lens.
        market_context = await load_active_market_context(session)
        if market_context:
            logger.info(f"Active market context: {[c['context_type'] for c in market_context]}")

        scored = 0
        errors = 0
        tier_counts = {
            "CONVICTION": 0, "HIGH": 0, "WATCH": 0,
            "SPECULATIVE": 0, "PASS": 0, "unscored": 0,
        }

        for i in range(0, len(entities), BATCH_SIZE):
            batch = entities[i:i + BATCH_SIZE]
            for entity in batch:
                try:
                    result = await score_entity(session, entity, market_context)
                    tier_counts[result.conviction_tier] = (
                        tier_counts.get(result.conviction_tier, 0) + 1
                    )
                    scored += 1

                    if result.conviction_tier in ("CONVICTION", "HIGH"):
                        logger.info(
                            f"  ★ {entity.name} — {result.conviction_tier} "
                            f"({result.composite_score:.3f}) — "
                            f"{result.active_lenses}/5 lenses — "
                            f"{result.top_lens or 'none'}"
                        )
                except Exception as e:
                    logger.error(f"Error scoring {entity.name}: {e}")
                    errors += 1

            await session.commit()
            logger.info(
                f"Committed batch {i // BATCH_SIZE + 1} "
                f"({scored} scored, {errors} errors)"
            )
            # Respect SEC rate limits between batches
            await asyncio.sleep(1.0)

    async with AsyncSessionLocal() as snap_session:
        snap_count = await write_daily_snapshots(snap_session)
        logger.info(f"Daily score snapshots written: {snap_count}")

    logger.info("=" * 60)
    logger.info(f"1000x SCREENING COMPLETE — {scored} scored, {errors} errors")
    logger.info(f"Tier breakdown: {tier_counts}")
    watchlist = tier_counts.get("CONVICTION", 0) + tier_counts.get("HIGH", 0)
    logger.info(f"Watchlist additions: {watchlist}")
    logger.info("=" * 60)


async def run_loop():
    """Run screening on a daily loop."""
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_screening_batch()
            await report_heartbeat("screener-1000x", duration_seconds=_time.time()-_start, interval_hours=24)
        except Exception as e:
            logger.error(f"Screening batch failed: {e}")
            await report_heartbeat("screener-1000x", error=str(e), interval_hours=24)
        logger.info("Next 1000x screening run in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("screener-1000x", run_screening_batch))
    else:
        asyncio.run(run_loop())
