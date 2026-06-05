"""
Theme Lane — base definition (Sprint 7.1)

A "lane" is a megatrend → bottleneck → exposed-company thesis. It carries
everything the engine needs to (a) decide whether a company belongs to the lane,
(b) score it with lane-appropriate weights, and (c) flag lane-specific risks.

Lanes are code-as-config (not DB-driven) — they're versioned with the code and
referenced by `lane_id` everywhere else (candidate_lanes table, screener,
risk-filter, thesis engine).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Calibration lifecycle (Sprint 12) — replaces the old `calibrated: bool`.
#   unvalidated        — the lane's score is not shown to predict returns.
#   research_validated — backtest-suggestive (e.g. seed-backtest correlation) but
#                        NOT proven on live forward data. Still capped at DEEP_DIVE.
#   live_validated     — cleared the live bar on matured alerts. The ONLY status
#                        that unlocks SETUP_READY (see shared/scoring/buckets.py
#                        and shared/scoring/calibration.py for the thresholds).
CALIBRATION_STATUSES = ("unvalidated", "research_validated", "live_validated")


@dataclass(frozen=True)
class UniverseFilter:
    """Which public companies are even eligible for this lane."""
    market_cap_min_usd: Optional[float] = None        # e.g. 15e6 — exclude sub-$15M shells
    market_cap_max_usd: Optional[float] = None        # e.g. 500e6 for the biotech micro-cap wedge
    sectors: tuple[str, ...] = ()                     # substring match against entity.sector (empty = any)
    exchanges: tuple[str, ...] = ()                   # e.g. ("NASDAQ", "NYSE") (empty = any)

    def matches(
        self,
        *,
        market_cap_usd: Optional[float],
        sector: Optional[str],
        exchange: Optional[str] = None,
    ) -> bool:
        if self.market_cap_min_usd is not None and (market_cap_usd or 0) < self.market_cap_min_usd:
            return False
        if self.market_cap_max_usd is not None and market_cap_usd is not None \
                and market_cap_usd > self.market_cap_max_usd:
            return False
        if self.sectors and sector:
            s = sector.lower()
            if not any(allowed.lower() in s for allowed in self.sectors):
                return False
        if self.exchanges and exchange:
            if not any(e.lower() == exchange.lower() for e in self.exchanges):
                return False
        return True


@dataclass(frozen=True)
class Lane:
    lane_id: str                                      # stable id, e.g. "L1_AI_INFRA"
    name: str                                         # human label
    megatrend: str                                    # one-line thesis, e.g. "AI training + inference explosion"

    # Bottlenecks: the scarce resources this megatrend depends on. Each bottleneck
    # maps to the keyword phrases that identify a company sitting on it — this is
    # how the lane-router fills candidate_lanes.bottleneck_exposure.
    bottlenecks: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # General lane keywords (union of all bottleneck keywords + thesis-level terms).
    keywords: tuple[str, ...] = ()

    # Catalyst event_types this lane cares about (extends catalyst_events.event_type).
    catalyst_types: tuple[str, ...] = ()

    # Per-lane lens weights — override the global screener weights. Must sum ~1.0.
    scoring_weights: dict[str, float] = field(default_factory=dict)

    # Lane-specific risk flags layered on top of the shared ones (Sprint 7.6 / 9.3).
    red_flags: tuple[str, ...] = ()

    universe_filters: UniverseFilter = field(default_factory=UniverseFilter)

    # Calibration lifecycle (Sprint 12). Only `live_validated` lanes may emit
    # SETUP_READY; the rest cap at DEEP_DIVE until proven on live forward data.
    calibration_status: str = "unvalidated"

    # Stats that justify the CURRENT status — filled in when a lane is promoted,
    # using the numbers `scripts/recompute_lane_calibration.py` reports. They make
    # each promotion auditable right here in the config (code-as-config).
    sample_size: int = 0                              # # matured alerts behind the status
    live_win_rate_90d: Optional[float] = None         # fraction up at 90d
    false_positive_rate: Optional[float] = None       # fraction materially negative at 90d
    median_forward_return_90d: Optional[float] = None # median 90d return of alerts

    def is_live_validated(self) -> bool:
        """Only live-validated lanes may graduate a candidate to SETUP_READY."""
        return self.calibration_status == "live_validated"

    def all_keywords(self) -> tuple[str, ...]:
        """Union of explicit keywords + every bottleneck's keywords (deduped)."""
        seen: dict[str, None] = {}
        for kw in self.keywords:
            seen[kw.lower()] = None
        for kws in self.bottlenecks.values():
            for kw in kws:
                seen[kw.lower()] = None
        return tuple(seen.keys())

    def match_score(self, text: str) -> float:
        """How strongly does `text` match this lane? 0.0–1.0 by keyword density."""
        if not text:
            return 0.0
        low = text.lower()
        kws = self.all_keywords()
        if not kws:
            return 0.0
        hits = sum(1 for kw in kws if kw in low)
        # 25% of keywords matched = max score (same shape as lens_demand_rider density*3 cap)
        return round(min((hits / len(kws)) * 4.0, 1.0), 4)

    def matched_bottlenecks(self, text: str) -> list[str]:
        """Which specific bottlenecks does `text` evidence exposure to?"""
        if not text:
            return []
        low = text.lower()
        out = []
        for bottleneck, kws in self.bottlenecks.items():
            if any(kw.lower() in low for kw in kws):
                out.append(bottleneck)
        return out

    def __post_init__(self) -> None:
        # Validate weights sum ~1.0 if provided (fail loud at import time).
        if self.scoring_weights:
            total = sum(self.scoring_weights.values())
            if not (0.99 <= total <= 1.01):
                raise ValueError(
                    f"Lane {self.lane_id} scoring_weights sum to {total:.4f}, expected ~1.0"
                )
        # Fail loud on a mistyped calibration status (it gates real alerts).
        if self.calibration_status not in CALIBRATION_STATUSES:
            raise ValueError(
                f"Lane {self.lane_id} calibration_status={self.calibration_status!r}, "
                f"expected one of {CALIBRATION_STATUSES}"
            )
