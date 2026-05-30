"""
Theme Lanes registry (Sprint 7.1)

Two active lanes at launch: L1 AI Infrastructure, L2 Biotech Catalysts.
Queued lanes (crypto→AI, physical AI, energy) get added here as they activate.

Usage:
    from shared.lanes import ALL_LANES, get_lane, match_lanes

    lanes = match_lanes(
        text=filing_text + " " + business_description,
        sector=entity.sector,
        market_cap_usd=market_cap,
    )
    # -> [LaneMatch(lane_id="L1_AI_INFRA", score=0.42, bottlenecks=["power"]), ...]
"""
from __future__ import annotations

from dataclasses import dataclass

from .ai_infra import L1_AI_INFRA
from .base import Lane, UniverseFilter
from .biotech import L2_BIOTECH

# Order matters only for stable tie-breaking; both are "active".
ALL_LANES: tuple[Lane, ...] = (L1_AI_INFRA, L2_BIOTECH)

_BY_ID: dict[str, Lane] = {lane.lane_id: lane for lane in ALL_LANES}

# Minimum match score for a candidate to be assigned to a lane.
LANE_MATCH_THRESHOLD = 0.08


@dataclass(frozen=True)
class LaneMatch:
    lane_id: str
    score: float                 # 0.0–1.0 keyword-density match
    bottlenecks: list[str]       # which bottleneck(s) the company sits on


def get_lane(lane_id: str) -> Lane:
    """Return the Lane for an id, or raise KeyError."""
    return _BY_ID[lane_id]


def lane_ids() -> list[str]:
    return list(_BY_ID.keys())


def match_lanes(
    *,
    text: str,
    sector: str | None = None,
    market_cap_usd: float | None = None,
    exchange: str | None = None,
    threshold: float = LANE_MATCH_THRESHOLD,
) -> list[LaneMatch]:
    """Assign a company to zero or more lanes.

    A lane matches when BOTH:
      - the company passes the lane's universe filter (market cap / sector), AND
      - keyword match score >= threshold.

    Returns matches sorted by score descending. A company can match multiple
    lanes (e.g. IREN = AI-infra power AND crypto-miner pivot once L3 is active).
    """
    out: list[LaneMatch] = []
    for lane in ALL_LANES:
        if not lane.universe_filters.matches(
            market_cap_usd=market_cap_usd, sector=sector, exchange=exchange
        ):
            continue
        score = lane.match_score(text)
        if score >= threshold:
            out.append(
                LaneMatch(
                    lane_id=lane.lane_id,
                    score=score,
                    bottlenecks=lane.matched_bottlenecks(text),
                )
            )
    out.sort(key=lambda m: m.score, reverse=True)
    return out


__all__ = [
    "Lane",
    "UniverseFilter",
    "LaneMatch",
    "ALL_LANES",
    "LANE_MATCH_THRESHOLD",
    "L1_AI_INFRA",
    "L2_BIOTECH",
    "get_lane",
    "lane_ids",
    "match_lanes",
]
