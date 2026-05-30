"""
Multi-axis scoring (Sprint 9.4) — pure, testable.

Replaces the single composite with a 5-axis vector (each 0–100). The composite
is kept for back-compat; buckets (9.5) and alerts (9.6) read the vector.

  Opportunity  — how asymmetric the setup is (lens convergence × small-cap leverage)
  Risk         — dilution / runway / red flags (higher = riskier)
  Timing       — is the catalyst close enough to act on
  Confidence   — how reliable/corroborated the evidence is
  Tradability  — can you enter/exit without getting trapped (float, volume, liquidity)

Each is computed per (candidate, lane) so the same company can score differently
in different lanes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, x)), 1)


@dataclass
class AxisScores:
    opportunity: float
    risk: float
    timing: float
    confidence: float
    tradability: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def score_opportunity(composite_score: float, market_cap_usd: Optional[float]) -> float:
    """Asymmetry: strong multi-lens setup on a small, ignored name = max upside.

    composite_score is the lane composite (0–1). Smaller market cap multiplies
    the asymmetry (more room to re-rate).
    """
    base = composite_score * 100.0
    if market_cap_usd is None:
        leverage = 1.0
    else:
        mc_m = market_cap_usd / 1e6
        if mc_m < 100:
            leverage = 1.25
        elif mc_m < 500:
            leverage = 1.15
        elif mc_m < 2000:
            leverage = 1.05
        elif mc_m < 10000:
            leverage = 0.95
        else:
            leverage = 0.85
    return _clamp(base * leverage)


def score_risk(
    *,
    red_flag_count: int,
    has_critical_flag: bool,
    cash_runway_months: Optional[float],
    short_pct_float: Optional[float],
    market_cap_usd: Optional[float],
) -> float:
    """Higher = riskier. Critical flags floor the score high."""
    if has_critical_flag:
        return _clamp(85.0 + 5.0 * red_flag_count)

    risk = 20.0
    risk += 8.0 * red_flag_count
    # Cash runway: < 6 months is a survival risk
    if cash_runway_months is not None:
        if cash_runway_months < 6:
            risk += 30
        elif cash_runway_months < 12:
            risk += 15
    # Heavy short interest cuts both ways — squeeze fuel but also smart-money bearishness
    if short_pct_float is not None and short_pct_float > 0.30:
        risk += 10
    # Nano caps are manipulation-prone
    if market_cap_usd is not None and market_cap_usd < 50e6:
        risk += 15
    return _clamp(risk)


def score_timing(catalyst_proximity_days: Optional[int]) -> float:
    """Closer dated catalyst = higher timing score. None = no dated catalyst = low."""
    if catalyst_proximity_days is None:
        return 20.0
    d = catalyst_proximity_days
    if d < 0:
        return 30.0          # catalyst passed — stale
    if d <= 14:
        return 95.0
    if d <= 30:
        return 88.0
    if d <= 90:
        return 72.0
    if d <= 180:
        return 55.0
    return 35.0              # > 180d out


def score_confidence(
    *,
    active_lenses: int,
    evidence_count: int,
    institutional_confirmation: bool,
) -> float:
    """How corroborated the thesis is: more lenses + more evidence + smart-money confirm."""
    conf = 15.0
    conf += 12.0 * active_lenses          # up to ~60 for 5 lenses
    conf += min(evidence_count, 8) * 3.0  # up to 24
    if institutional_confirmation:
        conf += 10
    return _clamp(conf)


def score_tradability(
    *,
    market_cap_usd: Optional[float],
    volume_ratio: Optional[float],
    float_shares: Optional[float],
    days_to_cover: Optional[float],
) -> float:
    """Can you actually enter/exit? Tiny float + no volume = trap risk = low score."""
    trade = 50.0
    # Volume relative to its own average — awakening volume aids entry/exit
    if volume_ratio is not None:
        if volume_ratio >= 2.0:
            trade += 20
        elif volume_ratio >= 1.0:
            trade += 10
        elif volume_ratio < 0.3:
            trade -= 25     # dead volume = trap
    # Absolute liquidity floor by market cap
    if market_cap_usd is not None:
        if market_cap_usd < 25e6:
            trade -= 25
        elif market_cap_usd < 100e6:
            trade -= 10
        elif market_cap_usd > 1e9:
            trade += 15
    # Extreme short squeeze can make exits violent (lower tradability)
    if days_to_cover is not None and days_to_cover > 10:
        trade -= 10
    return _clamp(trade)


def compute_axes(
    *,
    composite_score: float,
    active_lenses: int,
    market_cap_usd: Optional[float] = None,
    cash_runway_months: Optional[float] = None,
    short_pct_float: Optional[float] = None,
    float_shares: Optional[float] = None,
    days_to_cover: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    catalyst_proximity_days: Optional[int] = None,
    evidence_count: int = 0,
    institutional_confirmation: bool = False,
    red_flag_count: int = 0,
    has_critical_flag: bool = False,
) -> AxisScores:
    """Compute all five axes for one (candidate, lane)."""
    return AxisScores(
        opportunity=score_opportunity(composite_score, market_cap_usd),
        risk=score_risk(
            red_flag_count=red_flag_count,
            has_critical_flag=has_critical_flag,
            cash_runway_months=cash_runway_months,
            short_pct_float=short_pct_float,
            market_cap_usd=market_cap_usd,
        ),
        timing=score_timing(catalyst_proximity_days),
        confidence=score_confidence(
            active_lenses=active_lenses,
            evidence_count=evidence_count,
            institutional_confirmation=institutional_confirmation,
        ),
        tradability=score_tradability(
            market_cap_usd=market_cap_usd,
            volume_ratio=volume_ratio,
            float_shares=float_shares,
            days_to_cover=days_to_cover,
        ),
    )
