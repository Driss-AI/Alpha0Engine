"""
Thesis generator (Sprint 9.2) — deterministic, testable.

Produces the structured "why now" narrative the alert template (9.6) requires.
Rule-based (not LLM) so it's reproducible and every claim traces to data we hold.

Output per (candidate, lane) has five mandatory fields:
  megatrend   — the wave (from the lane)
  bottleneck  — the scarce resource the company sits on (from candidate_lanes)
  exposure    — how this company is exposed to that bottleneck
  evidence    — bullet list, each with a source_url
  why_now     — dated catalyst + market mechanics, one sentence

Hard rule: if there is no dated catalyst, `why_now` is downgraded and
`has_dated_catalyst=False` so the bucket classifier can't promote it to SETUP READY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from shared.lanes import get_lane


@dataclass
class Thesis:
    ticker: str
    company: Optional[str]
    lane_id: str
    megatrend: str
    bottleneck: str
    exposure: str
    evidence: list[dict[str, Any]] = field(default_factory=list)   # [{summary, source_url}]
    why_now: str = ""
    has_dated_catalyst: bool = False
    catalyst_type: Optional[str] = None
    catalyst_date: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "company": self.company,
            "lane_id": self.lane_id,
            "megatrend": self.megatrend,
            "bottleneck": self.bottleneck,
            "exposure": self.exposure,
            "evidence": self.evidence,
            "why_now": self.why_now,
            "has_dated_catalyst": self.has_dated_catalyst,
            "catalyst_type": self.catalyst_type,
            "catalyst_date": self.catalyst_date,
        }


def _humanize_bottleneck(bottleneck: str) -> str:
    return bottleneck.replace("_", " ")


def build_thesis(
    *,
    ticker: str,
    company: Optional[str],
    lane_id: str,
    bottlenecks: list[str],
    evidence: list[dict[str, Any]],
    nearest_catalyst: Optional[dict[str, Any]] = None,
    volume_ratio: Optional[float] = None,
    short_pct_float: Optional[float] = None,
) -> Thesis:
    """Construct a structured thesis.

    Args:
        bottlenecks: from candidate_lanes.bottleneck_exposure
        evidence: [{summary, source_url, source}] rows for this candidate+lane
        nearest_catalyst: {catalyst_type, expected_date (ISO str or date), title} or None
    """
    lane = get_lane(lane_id)
    primary_bottleneck = bottlenecks[0] if bottlenecks else (
        next(iter(lane.bottlenecks), "the supply chain")
    )
    bn_human = _humanize_bottleneck(primary_bottleneck)

    exposure = (
        f"{company or ticker} sits on the {bn_human} bottleneck of "
        f"{lane.name.lower()} — {lane.megatrend.lower()}."
    )

    # ── why now ──
    has_dated = False
    catalyst_type = None
    catalyst_date = None
    mechanics_bits = []
    if volume_ratio is not None and volume_ratio >= 2.0:
        mechanics_bits.append(f"volume {volume_ratio:.1f}x its 30-day average")
    if short_pct_float is not None and short_pct_float >= 0.20:
        mechanics_bits.append(f"short interest {short_pct_float * 100:.0f}% of float")
    mechanics = ", ".join(mechanics_bits)

    if nearest_catalyst and nearest_catalyst.get("expected_date"):
        has_dated = True
        catalyst_type = nearest_catalyst.get("catalyst_type")
        ed = nearest_catalyst["expected_date"]
        catalyst_date = ed.isoformat() if isinstance(ed, date) else str(ed)
        why = f"{catalyst_type or 'catalyst'} dated {catalyst_date}"
        if mechanics:
            why += f"; {mechanics}"
        why_now = why[0].upper() + why[1:] + "."
    else:
        # No dated catalyst — cannot be SETUP READY.
        if mechanics:
            why_now = (f"No dated catalyst yet; market mechanics only ({mechanics}). "
                       f"Needs a confirmed event before action.")
        else:
            why_now = ("No dated catalyst and no mechanical confirmation yet — "
                       "thesis is structural only.")

    return Thesis(
        ticker=ticker,
        company=company,
        lane_id=lane_id,
        megatrend=lane.megatrend,
        bottleneck=bn_human,
        exposure=exposure,
        evidence=evidence,
        why_now=why_now,
        has_dated_catalyst=has_dated,
        catalyst_type=catalyst_type,
        catalyst_date=catalyst_date,
    )
