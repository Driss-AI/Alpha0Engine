"""
Evidence Collector — Brain Module 2
=====================================
For each candidate from the scanner, gathers ALL relevant evidence
from the database into a structured bundle. This is what the LLM
receives — it can ONLY reference data from this bundle, never its
training knowledge.

Evidence sources:
  - signals (all types: patents, filings, insider trades, etc.)
  - equity_screens (5-lens scores and details)
  - fundamental_scores (moat, margins, growth)
  - risk_assessments (hype gap, illiquidity, concentration)
  - catalyst_events (upcoming binary events)
  - ticker_timeline (recent event history)
  - company_news (when available)

Output: EvidenceBundle dict ready for LLM consumption.
Every piece of evidence carries a source_id for citation.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.entities import Entity
from shared.schemas.signals import Signal
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.fundamentals import FundamentalScore
from shared.schemas.risk import RiskAssessment
from shared.schemas.catalyst_event import CatalystEvent
from shared.schemas.ticker_timeline import TickerTimeline
from shared.schemas.company_news import CompanyNews

logger = logging.getLogger("brain.evidence")

# How far back to look for signals and timeline events
SIGNAL_LOOKBACK_DAYS = 90
TIMELINE_LOOKBACK_DAYS = 60
NEWS_LOOKBACK_DAYS = 30


async def _collect_entity(session: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    """Fetch core entity record."""
    result = await session.exec(select(Entity).where(Entity.id == entity_id))
    entity = result.first()
    if not entity:
        return None
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "ticker": entity.ticker,
        "cik": entity.cik,
        "entity_type": entity.entity_type,
        "sector": entity.sector,
        "subsector": entity.subsector,
        "hq_country": entity.hq_country,
        "founded_year": entity.founded_year,
        "description": entity.description,
    }


async def _collect_signals(
    session: AsyncSession,
    entity_id: str,
) -> List[Dict[str, Any]]:
    """Fetch recent signals, sorted by date descending."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    result = await session.exec(
        select(Signal)
        .where(Signal.entity_id == entity_id, Signal.signal_date >= cutoff)
        .order_by(col(Signal.signal_date).desc())
        .limit(100)
    )
    return [
        {
            "source_id": f"signal:{s.id}",
            "type": s.signal_type,
            "date": s.signal_date.isoformat() if s.signal_date else None,
            "value": s.value,
            "source": s.source,
            "notes": s.notes,
            "data": s.raw_data or {},
        }
        for s in result.all()
    ]


async def _collect_screener(
    session: AsyncSession,
    entity_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch 5-lens equity screen data."""
    result = await session.exec(
        select(EquityScreen).where(EquityScreen.entity_id == entity_id)
    )
    screen = result.first()
    if not screen:
        return None
    return {
        "source_id": f"screen:{screen.id}",
        "composite_score": screen.composite_score,
        "conviction_tier": screen.conviction_tier,
        "active_lenses": screen.active_lenses,
        "top_lens": screen.top_lens,
        "screening_notes": screen.screening_notes,
        "on_watchlist": screen.on_watchlist,
        "market_cap_usd": screen.market_cap_usd,
        "lenses": {
            "binary_catalyst": {
                "score": screen.catalyst_score,
                "type": screen.catalyst_type,
                "proximity_days": screen.catalyst_proximity_days,
                "details": screen.catalyst_details or {},
            },
            "earnings_inflection": {
                "score": screen.earnings_score,
                "trajectory": screen.eps_trajectory,
                "quarters_to_profit": screen.quarters_to_profit,
                "revenue_acceleration": screen.revenue_acceleration,
                "margin_expansion": screen.margin_expansion_rate,
                "details": screen.earnings_details or {},
            },
            "demand_rider": {
                "score": screen.demand_score,
                "megatrend": screen.megatrend_alignment,
                "theme_strength": screen.theme_strength,
                "institutional_neglect": screen.institutional_neglect,
                "details": screen.demand_details or {},
            },
            "float_mechanics": {
                "score": screen.float_score,
                "category": screen.float_category,
                "float_shares": screen.float_shares,
                "short_interest": screen.short_interest,
                "short_pct_float": screen.short_pct_float,
                "squeeze_potential": screen.squeeze_potential,
                "days_to_cover": screen.days_to_cover,
                "details": screen.float_details or {},
            },
            "smart_money": {
                "score": screen.smart_money_score,
                "institutional_buys": screen.institutional_buys_13f,
                "insider_buys": screen.insider_buys_form4,
                "insider_buy_value": screen.insider_buy_value_usd,
                "details": screen.smart_money_details or {},
            },
        },
        "screened_at": screen.screened_at.isoformat() if screen.screened_at else None,
    }


async def _collect_fundamentals(
    session: AsyncSession,
    entity_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch fundamental score data."""
    result = await session.exec(
        select(FundamentalScore).where(FundamentalScore.entity_id == entity_id)
    )
    fs = result.first()
    if not fs:
        return None
    return {
        "source_id": f"fundamental:{fs.id}",
        "moat_score": fs.moat_score,
        "patent_strength": fs.patent_strength,
        "talent_density": fs.talent_density,
        "github_momentum": fs.github_momentum,
        "market_cap_usd": fs.market_cap_usd,
        "revenue_growth_yoy": fs.revenue_growth_yoy,
        "gross_margin": fs.gross_margin,
        "gross_margin_velocity": fs.gross_margin_velocity,
        "cash_runway_months": fs.cash_runway_months,
        "rule_of_40": fs.rule_of_40,
        "fundamental_score": fs.fundamental_score,
        "screening_tier": fs.screening_tier,
        "scored_at": fs.scored_at.isoformat() if fs.scored_at else None,
    }


async def _collect_risk(
    session: AsyncSession,
    entity_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch risk assessment data."""
    result = await session.exec(
        select(RiskAssessment).where(RiskAssessment.entity_id == entity_id)
    )
    risk = result.first()
    if not risk:
        return None
    return {
        "source_id": f"risk:{risk.id}",
        "risk_score": risk.risk_score,
        "risk_tier": risk.risk_tier,
        "hype_score": risk.hype_score,
        "substance_score": risk.substance_score,
        "hype_gap": risk.hype_gap,
        "hype_flag": risk.hype_flag,
        "illiquidity_score": risk.illiquidity_score,
        "illiquidity_flag": risk.illiquidity_flag,
        "signal_concentration": risk.signal_concentration,
        "risk_flags": risk.risk_flags or {},
        "risk_notes": risk.risk_notes,
        "assessed_at": risk.assessed_at.isoformat() if risk.assessed_at else None,
    }


async def _collect_catalysts(
    session: AsyncSession,
    entity_id: str,
    ticker: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch upcoming and recent catalyst events."""
    query = select(CatalystEvent).where(CatalystEvent.entity_id == entity_id)
    if ticker:
        query = query.where(CatalystEvent.ticker == ticker)
    query = query.order_by(col(CatalystEvent.expected_date).desc()).limit(20)

    result = await session.exec(query)
    return [
        {
            "source_id": f"catalyst:{c.id}",
            "type": c.catalyst_type,
            "title": c.title,
            "expected_date": c.expected_date.isoformat() if c.expected_date else None,
            "status": c.status,
            "impact_score": c.impact_score,
            "details": c.details or {},
        }
        for c in result.all()
    ]


async def _collect_timeline(
    session: AsyncSession,
    entity_id: str,
    ticker: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch recent timeline events."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TIMELINE_LOOKBACK_DAYS)).date()

    query = select(TickerTimeline).where(TickerTimeline.event_date >= cutoff)
    if entity_id:
        query = query.where(TickerTimeline.entity_id == entity_id)
    elif ticker:
        query = query.where(TickerTimeline.ticker == ticker)
    else:
        return []

    query = query.order_by(col(TickerTimeline.event_date).desc()).limit(30)
    result = await session.exec(query)
    return [
        {
            "source_id": f"timeline:{t.id}",
            "event_type": t.event_type,
            "title": t.event_title,
            "date": t.event_date.isoformat() if t.event_date else None,
            "source": t.source,
            "data": t.event_data or {},
        }
        for t in result.all()
    ]


async def _collect_news(
    session: AsyncSession,
    entity_id: str,
    ticker: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch recent news articles."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=NEWS_LOOKBACK_DAYS)

    query = select(CompanyNews).where(CompanyNews.created_at >= cutoff)
    if entity_id:
        query = query.where(CompanyNews.entity_id == entity_id)
    elif ticker:
        query = query.where(CompanyNews.ticker == ticker)
    else:
        return []

    query = query.order_by(col(CompanyNews.published_at).desc()).limit(20)
    result = await session.exec(query)
    return [
        {
            "source_id": f"news:{n.id}",
            "title": n.title,
            "summary": n.summary,
            "source": n.source,
            "sentiment": n.sentiment,
            "sentiment_score": n.sentiment_score,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "url": n.url,
        }
        for n in result.all()
    ]


def _compute_evidence_stats(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Compute summary statistics about the evidence bundle."""
    signals = bundle.get("signals", [])
    sources = set()
    signal_types = set()

    for s in signals:
        sources.add(s.get("source", "unknown"))
        signal_types.add(s.get("type", "unknown"))

    # Count total evidence pieces
    total_evidence = (
        len(signals) +
        (1 if bundle.get("screener") else 0) +
        (1 if bundle.get("fundamentals") else 0) +
        (1 if bundle.get("risk") else 0) +
        len(bundle.get("catalysts", [])) +
        len(bundle.get("timeline", [])) +
        len(bundle.get("news", []))
    )

    return {
        "total_evidence_pieces": total_evidence,
        "signal_count": len(signals),
        "source_diversity": len(sources),
        "signal_types": list(signal_types),
        "data_sources": list(sources),
        "has_screener": bundle.get("screener") is not None,
        "has_fundamentals": bundle.get("fundamentals") is not None,
        "has_risk": bundle.get("risk") is not None,
        "catalyst_count": len(bundle.get("catalysts", [])),
        "timeline_count": len(bundle.get("timeline", [])),
        "news_count": len(bundle.get("news", [])),
    }


async def collect_evidence(
    session: AsyncSession,
    entity_id: str,
    ticker: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Main entry point. Collects ALL evidence for an entity into a
    structured bundle ready for LLM analysis.

    The LLM must ONLY reference data from this bundle.
    Every piece carries a source_id for mandatory citation.

    Returns:
        EvidenceBundle dict with:
        - entity: core company info
        - signals: recent signals with source_ids
        - screener: 5-lens scores and details
        - fundamentals: moat and financial metrics
        - risk: risk assessment data
        - catalysts: upcoming binary events
        - timeline: recent event history
        - news: recent articles
        - stats: summary statistics
        - collected_at: timestamp
    """
    # Core entity info
    entity_data = await _collect_entity(session, entity_id)
    if not entity_data:
        logger.warning(f"Entity {entity_id} not found — skipping evidence collection")
        return None

    effective_ticker = ticker or entity_data.get("ticker")

    # Collect from all sources in parallel-ish (sequential for DB safety)
    signals = await _collect_signals(session, entity_id)
    screener = await _collect_screener(session, entity_id)
    fundamentals = await _collect_fundamentals(session, entity_id)
    risk = await _collect_risk(session, entity_id)
    catalysts = await _collect_catalysts(session, entity_id, effective_ticker)
    timeline = await _collect_timeline(session, entity_id, effective_ticker)
    news = await _collect_news(session, entity_id, effective_ticker)

    bundle = {
        "entity": entity_data,
        "signals": signals,
        "screener": screener,
        "fundamentals": fundamentals,
        "risk": risk,
        "catalysts": catalysts,
        "timeline": timeline,
        "news": news,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    # Add stats
    bundle["stats"] = _compute_evidence_stats(bundle)

    logger.info(
        f"Evidence collected for {entity_data['name']} ({effective_ticker}): "
        f"{bundle['stats']['total_evidence_pieces']} pieces from "
        f"{bundle['stats']['source_diversity']} sources"
    )

    return bundle


async def collect_evidence_batch(
    session: AsyncSession,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Collect evidence for a batch of candidates from the scanner.

    Returns list of (candidate, evidence_bundle) tuples.
    Skips candidates with insufficient evidence.
    """
    MIN_EVIDENCE_PIECES = 2  # Need at least some data to analyze

    results = []
    for candidate in candidates:
        entity_id = candidate["entity_id"]
        ticker = candidate.get("ticker")

        try:
            bundle = await collect_evidence(session, entity_id, ticker)
            if not bundle:
                continue

            # Skip if insufficient evidence
            if bundle["stats"]["total_evidence_pieces"] < MIN_EVIDENCE_PIECES:
                logger.debug(
                    f"Skipping {candidate.get('company_name', entity_id)}: "
                    f"only {bundle['stats']['total_evidence_pieces']} evidence pieces"
                )
                continue

            results.append({
                "candidate": candidate,
                "evidence": bundle,
            })
        except Exception as e:
            logger.error(f"Evidence collection failed for {entity_id}: {e}")
            continue

    logger.info(
        f"Evidence batch complete: {len(results)}/{len(candidates)} "
        f"candidates have sufficient evidence"
    )

    return results
