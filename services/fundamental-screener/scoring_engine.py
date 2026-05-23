"""
Composite Scoring Engine
=========================
Combines moat score, public metrics, and private proxies
into a single fundamental_score (0.0 – 1.0) with a tier (S/A/B/C/D).

Scoring Philosophy:
  - S tier (>0.80): Exceptional moat + strong economics = "conviction buy"
  - A tier (>0.65): Strong on multiple dimensions = "high interest"
  - B tier (>0.45): Promising but gaps in data or metrics = "watchlist"
  - C tier (>0.25): Early / thin data = "monitor"
  - D tier (≤0.25): Weak signals or concerning economics = "pass"
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _score_rd_intensity(rd_to_mktcap: Optional[float]) -> float:
    """High R&D / market cap = investing in future growth."""
    if rd_to_mktcap is None:
        return 0.0
    if rd_to_mktcap > 0.30:
        return 1.0
    if rd_to_mktcap > 0.15:
        return 0.8
    if rd_to_mktcap > 0.08:
        return 0.6
    if rd_to_mktcap > 0.03:
        return 0.3
    return 0.1


def _score_gross_margin(gm: Optional[float]) -> float:
    """Software-like margins (>70%) are best for asymmetric returns."""
    if gm is None:
        return 0.0
    if gm > 0.80:
        return 1.0
    if gm > 0.70:
        return 0.85
    if gm > 0.50:
        return 0.60
    if gm > 0.30:
        return 0.35
    return 0.15


def _score_gm_velocity(velocity: Optional[float]) -> float:
    """Positive margin expansion = improving unit economics."""
    if velocity is None:
        return 0.0
    if velocity > 0.05:
        return 1.0
    if velocity > 0.02:
        return 0.7
    if velocity > 0.0:
        return 0.5
    if velocity > -0.02:
        return 0.3
    return 0.1  # Contracting margins


def _score_cash_runway(months: Optional[float]) -> float:
    """Companies need enough runway to execute. <12 months = danger."""
    if months is None:
        return 0.0
    if months > 36:
        return 1.0
    if months > 24:
        return 0.8
    if months > 18:
        return 0.6
    if months > 12:
        return 0.4
    if months > 6:
        return 0.2
    return 0.05  # Critical burn


def _score_revenue_growth(yoy: Optional[float]) -> float:
    """Hyper-growth (>100% YoY) = breakout potential."""
    if yoy is None:
        return 0.0
    if yoy > 1.0:
        return 1.0
    if yoy > 0.50:
        return 0.8
    if yoy > 0.25:
        return 0.6
    if yoy > 0.10:
        return 0.4
    if yoy > 0.0:
        return 0.2
    return 0.05


def _score_rule_of_40(r40: Optional[float]) -> float:
    """Rule of 40: revenue growth % + profit margin %. >40 is good."""
    if r40 is None:
        return 0.0
    if r40 > 60:
        return 1.0
    if r40 > 40:
        return 0.8
    if r40 > 20:
        return 0.5
    if r40 > 0:
        return 0.3
    return 0.1


def _score_secondary_discount(pct: Optional[float]) -> float:
    """
    Secondary premium/discount signal.
    Premium (positive) = strong demand.
    Deep discount = potential value opportunity OR red flag.
    """
    if pct is None:
        return 0.0
    if pct > 20:  # 20%+ premium
        return 0.9
    if pct > 0:
        return 0.7
    if pct > -10:
        return 0.5
    if pct > -30:
        return 0.35
    return 0.15  # Deep discount — might be distress


def _score_private_runway(months: Optional[float]) -> float:
    """Private runway estimation. Same logic as public but more forgiving."""
    if months is None:
        return 0.3  # Unknown = slight risk discount
    if months > 24:
        return 1.0
    if months > 18:
        return 0.8
    if months > 12:
        return 0.5
    if months > 6:
        return 0.25
    return 0.05


def compute_fundamental_score(
    moat: Dict[str, float],
    public_metrics: Optional[Dict[str, Any]] = None,
    private_metrics: Optional[Dict[str, Any]] = None,
    entity_type: str = "private",
) -> Dict[str, Any]:
    """
    Master scoring function. Combines all dimensions.

    Returns:
        fundamental_score (0.0 – 1.0)
        screening_tier (S/A/B/C/D)
        component breakdown
    """
    moat_score = moat.get("moat_score", 0.0)

    if entity_type == "public" and public_metrics and "error" not in public_metrics:
        # ── Public company scoring ─────────────────────────
        rd_mktcap = None
        if public_metrics.get("rd_expense") and public_metrics.get("market_cap_usd"):
            rd_mktcap = public_metrics["rd_expense"] / public_metrics["market_cap_usd"]

        components = {
            "moat": moat_score,
            "rd_intensity": _score_rd_intensity(rd_mktcap),
            "gross_margin": _score_gross_margin(public_metrics.get("gross_margin")),
            "gm_velocity": _score_gm_velocity(public_metrics.get("gross_margin_velocity")),
            "cash_runway": _score_cash_runway(public_metrics.get("cash_runway_months")),
            "revenue_growth": _score_revenue_growth(public_metrics.get("revenue_growth_yoy")),
            "rule_of_40": _score_rule_of_40(public_metrics.get("rule_of_40")),
        }

        weights = {
            "moat": 0.25,
            "rd_intensity": 0.12,
            "gross_margin": 0.15,
            "gm_velocity": 0.08,
            "cash_runway": 0.10,
            "revenue_growth": 0.18,
            "rule_of_40": 0.12,
        }

    elif entity_type == "private" and private_metrics:
        # ── Private company scoring ────────────────────────
        components = {
            "moat": moat_score,
            "secondary_signal": _score_secondary_discount(private_metrics.get("secondary_vs_primary")),
            "estimated_runway": _score_private_runway(private_metrics.get("estimated_runway_months")),
            "funding_signal": min(
                (private_metrics.get("total_raised") or 0) / 100_000_000, 1.0
            ),  # Normalize: $100M+ = 1.0
        }

        weights = {
            "moat": 0.40,
            "secondary_signal": 0.25,
            "estimated_runway": 0.20,
            "funding_signal": 0.15,
        }

    else:
        # ── Moat-only scoring (limited data) ───────────────
        components = {"moat": moat_score}
        weights = {"moat": 1.0}

    # Weighted composite
    score = sum(components[k] * weights[k] for k in components)
    score = round(min(max(score, 0.0), 1.0), 4)

    # Assign tier
    if score > 0.80:
        tier = "S"
    elif score > 0.65:
        tier = "A"
    elif score > 0.45:
        tier = "B"
    elif score > 0.25:
        tier = "C"
    else:
        tier = "D"

    notes_parts = []
    for k, v in components.items():
        if v >= 0.8:
            notes_parts.append(f"{k}=strong")
        elif v <= 0.2:
            notes_parts.append(f"{k}=weak")

    return {
        "fundamental_score": score,
        "screening_tier": tier,
        "components": components,
        "weights": weights,
        "screening_notes": "; ".join(notes_parts) if notes_parts else "balanced",
    }
