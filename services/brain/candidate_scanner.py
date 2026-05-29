"""
Candidate Scanner — Brain Module 1
====================================
Reduces 10,000+ entities down to a short list of candidates worth
deep AI analysis. Runs daily before the evidence collector.

Selection criteria (OR logic — any path qualifies):
  1. High screener score: composite_score >= 0.35 AND active_lenses >= 2
  2. Signal burst: 3+ new signals in the last 7 days
  3. Catalyst proximity: upcoming catalyst within 30 days
  4. Multi-lens convergence: 3+ lenses active (regardless of composite)
  5. Earnings inflection: earnings_score >= 0.5 (turnaround plays)

Output: list of candidate dicts with entity_id, ticker, reason, priority.
Most days this returns 5–30 candidates. Zero is a valid answer.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from sqlmodel import select, col, func
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.entities import Entity
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.signals import Signal
from shared.schemas.catalyst_event import CatalystEvent

logger = logging.getLogger("brain.scanner")

# ── Thresholds ──────────────────────────────────────────────
MIN_COMPOSITE_SCORE = 0.35
MIN_LENSES_FOR_COMPOSITE = 2
SIGNAL_BURST_COUNT = 3
SIGNAL_BURST_DAYS = 7
CATALYST_PROXIMITY_DAYS = 30
MIN_LENSES_CONVERGENCE = 3
MIN_EARNINGS_SCORE = 0.5
MAX_CANDIDATES = 50  # safety cap per run


async def _get_screener_candidates(session: AsyncSession) -> List[Dict[str, Any]]:
    """Path 1 & 4: High composite score or multi-lens convergence."""
    result = await session.exec(
        select(EquityScreen).where(
            (
                (EquityScreen.composite_score >= MIN_COMPOSITE_SCORE) &
                (EquityScreen.active_lenses >= MIN_LENSES_FOR_COMPOSITE)
            ) | (
                EquityScreen.active_lenses >= MIN_LENSES_CONVERGENCE
            )
        ).order_by(col(EquityScreen.composite_score).desc())
        .limit(MAX_CANDIDATES)
    )
    candidates = []
    for screen in result.all():
        reason = []
        if screen.composite_score >= MIN_COMPOSITE_SCORE and screen.active_lenses >= MIN_LENSES_FOR_COMPOSITE:
            reason.append(f"composite={screen.composite_score:.3f}, {screen.active_lenses} lenses")
        if screen.active_lenses >= MIN_LENSES_CONVERGENCE:
            reason.append(f"convergence: {screen.active_lenses}/5 lenses firing")
        candidates.append({
            "entity_id": screen.entity_id,
            "ticker": screen.ticker,
            "company_name": screen.company_name,
            "source": "screener",
            "reason": "; ".join(reason),
            "priority": screen.composite_score,
            "composite_score": screen.composite_score,
            "active_lenses": screen.active_lenses,
            "conviction_tier": screen.conviction_tier,
        })
    return candidates


async def _get_signal_burst_candidates(session: AsyncSession) -> List[Dict[str, Any]]:
    """Path 2: Entities with a burst of recent signals."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=SIGNAL_BURST_DAYS)

    result = await session.exec(
        select(
            Signal.entity_id,
            func.count(Signal.id).label("signal_count"),
        )
        .where(Signal.signal_date >= cutoff)
        .group_by(Signal.entity_id)
        .having(func.count(Signal.id) >= SIGNAL_BURST_COUNT)
    )

    candidates = []
    for entity_id, count in result.all():
        # Look up entity details
        entity_result = await session.exec(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = entity_result.first()
        if not entity or entity.entity_type != "public":
            continue

        candidates.append({
            "entity_id": entity_id,
            "ticker": entity.ticker,
            "company_name": entity.name,
            "source": "signal_burst",
            "reason": f"{count} signals in last {SIGNAL_BURST_DAYS} days",
            "priority": min(count / 10.0, 1.0),  # normalize
        })
    return candidates


async def _get_catalyst_candidates(session: AsyncSession) -> List[Dict[str, Any]]:
    """Path 3: Entities with upcoming catalysts within proximity window."""
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=CATALYST_PROXIMITY_DAYS)

    result = await session.exec(
        select(CatalystEvent).where(
            CatalystEvent.status == "upcoming",
            CatalystEvent.expected_date >= today,
            CatalystEvent.expected_date <= horizon,
        ).order_by(col(CatalystEvent.expected_date).asc())
    )

    candidates = []
    seen = set()
    for catalyst in result.all():
        if catalyst.entity_id in seen:
            continue
        seen.add(catalyst.entity_id)

        # Look up entity
        entity_result = await session.exec(
            select(Entity).where(Entity.id == catalyst.entity_id)
        )
        entity = entity_result.first()
        if not entity:
            continue

        days_away = (catalyst.expected_date - today).days
        candidates.append({
            "entity_id": catalyst.entity_id,
            "ticker": catalyst.ticker or (entity.ticker if entity else None),
            "company_name": entity.name if entity else None,
            "source": "catalyst_proximity",
            "reason": f"{catalyst.catalyst_type}: {catalyst.title} in {days_away}d",
            "priority": max(0.3, 1.0 - (days_away / CATALYST_PROXIMITY_DAYS)),
        })
    return candidates


async def _get_earnings_inflection_candidates(session: AsyncSession) -> List[Dict[str, Any]]:
    """Path 5: Entities showing earnings turnaround signals."""
    result = await session.exec(
        select(EquityScreen).where(
            EquityScreen.earnings_score >= MIN_EARNINGS_SCORE,
        ).order_by(col(EquityScreen.earnings_score).desc())
        .limit(20)
    )

    candidates = []
    for screen in result.all():
        candidates.append({
            "entity_id": screen.entity_id,
            "ticker": screen.ticker,
            "company_name": screen.company_name,
            "source": "earnings_inflection",
            "reason": f"earnings_score={screen.earnings_score:.3f}, trajectory={screen.eps_trajectory}",
            "priority": screen.earnings_score,
        })
    return candidates


def _deduplicate_and_rank(all_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge candidates from all paths. If an entity appears multiple times,
    combine reasons and boost priority (multi-path = stronger signal).
    """
    merged: Dict[str, Dict[str, Any]] = {}

    for c in all_candidates:
        eid = c["entity_id"]
        if eid in merged:
            existing = merged[eid]
            # Combine reasons
            existing["reasons"].append(f"[{c['source']}] {c['reason']}")
            # Boost priority for multi-path hits
            existing["priority"] = min(existing["priority"] + 0.15, 1.0)
            existing["path_count"] += 1
            # Keep highest composite if available
            if c.get("composite_score") and (
                not existing.get("composite_score") or
                c["composite_score"] > existing["composite_score"]
            ):
                existing["composite_score"] = c["composite_score"]
                existing["active_lenses"] = c.get("active_lenses")
                existing["conviction_tier"] = c.get("conviction_tier")
        else:
            merged[eid] = {
                "entity_id": eid,
                "ticker": c.get("ticker"),
                "company_name": c.get("company_name"),
                "reasons": [f"[{c['source']}] {c['reason']}"],
                "priority": c["priority"],
                "path_count": 1,
                "composite_score": c.get("composite_score"),
                "active_lenses": c.get("active_lenses"),
                "conviction_tier": c.get("conviction_tier"),
            }

    # Sort by priority (highest first), then by path_count
    ranked = sorted(
        merged.values(),
        key=lambda x: (x["priority"], x["path_count"]),
        reverse=True,
    )

    return ranked[:MAX_CANDIDATES]


async def scan_candidates(session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Main entry point. Scans all paths and returns a ranked, deduplicated
    list of candidates for the evidence collector.

    Returns:
        List of candidate dicts, each with:
        - entity_id, ticker, company_name
        - reasons: list of why this entity qualified
        - priority: 0.0-1.0
        - path_count: how many selection paths matched
        - composite_score, active_lenses, conviction_tier (if available)
    """
    logger.info("Scanning for Brain candidates...")

    # Run all paths
    screener = await _get_screener_candidates(session)
    logger.info(f"  Screener path: {len(screener)} candidates")

    bursts = await _get_signal_burst_candidates(session)
    logger.info(f"  Signal burst path: {len(bursts)} candidates")

    catalysts = await _get_catalyst_candidates(session)
    logger.info(f"  Catalyst path: {len(catalysts)} candidates")

    earnings = await _get_earnings_inflection_candidates(session)
    logger.info(f"  Earnings inflection path: {len(earnings)} candidates")

    # Merge and rank
    all_candidates = screener + bursts + catalysts + earnings
    ranked = _deduplicate_and_rank(all_candidates)

    multi_path = sum(1 for c in ranked if c["path_count"] > 1)
    logger.info(
        f"Scan complete: {len(ranked)} unique candidates "
        f"({multi_path} multi-path hits) from {len(all_candidates)} raw matches"
    )

    return ranked
