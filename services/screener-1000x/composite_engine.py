"""
1000x Composite Scoring Engine
================================
Combines all five lens scores into a unified conviction score (0.0 – 1.0).

Tiering:
  - CONVICTION (>0.75): Multiple lenses firing, strong setup = immediate action
  - HIGH (>0.55): 2-3 strong lenses = deep dive candidate
  - WATCH (>0.35): Promising but incomplete setup = monitor
  - SPECULATIVE (>0.15): Single lens firing = high-risk/high-reward
  - PASS (≤0.15): No meaningful 1000x setup detected

Key insight: 1000x returns require MULTIPLE lenses firing simultaneously.
A catalyst alone isn't enough without float mechanics.
Earnings inflection alone isn't enough without demand tailwind.
The conviction score rewards convergence across lenses.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Lens Weights ────────────────────────────────────────────
# Each lens contributes to the composite.
# Equal base weight, but convergence bonuses reward multi-lens setups.
LENS_WEIGHTS = {
    "binary_catalyst": 0.25,    # Highest: binary events create the actual 1000x move
    "earnings_inflection": 0.20,  # Fundamental re-rating driver
    "demand_rider": 0.15,       # Trend tailwind amplifier
    "float_mechanics": 0.20,    # Mechanical amplifier of moves
    "smart_money": 0.20,        # Confirmation signal
}

# Minimum score for a lens to be considered "active"
LENS_ACTIVE_THRESHOLD = 0.30


def _count_active_lenses(scores: Dict[str, float]) -> int:
    """Count how many lenses are meaningfully firing."""
    return sum(1 for v in scores.values() if v >= LENS_ACTIVE_THRESHOLD)


def _convergence_bonus(scores: Dict[str, float]) -> float:
    """
    Bonus for multiple lenses firing together.
    2 lenses = small bonus, 3+ = significant, 5 = maximum.
    """
    active = _count_active_lenses(scores)
    if active >= 5:
        return 0.15
    if active >= 4:
        return 0.12
    if active >= 3:
        return 0.08
    if active >= 2:
        return 0.04
    return 0.0


def _synergy_bonus(scores: Dict[str, float]) -> float:
    """
    Specific lens combinations that are especially powerful.
    """
    bonus = 0.0

    # SPRB pattern: binary catalyst + low float = explosive move
    if scores["binary_catalyst"] > 0.5 and scores["float_mechanics"] > 0.5:
        bonus += 0.05

    # SNDK pattern: earnings inflection + demand rider = sustained re-rating
    if scores["earnings_inflection"] > 0.5 and scores["demand_rider"] > 0.5:
        bonus += 0.04

    # Confirmation: smart money + any strong lens = validated setup
    if scores["smart_money"] > 0.5:
        strong_lenses = sum(1 for k, v in scores.items() if k != "smart_money" and v > 0.5)
        if strong_lenses >= 2:
            bonus += 0.05
        elif strong_lenses >= 1:
            bonus += 0.03

    # Triple threat: catalyst + float + smart money = max squeeze
    if (scores["binary_catalyst"] > 0.4 and
        scores["float_mechanics"] > 0.4 and
        scores["smart_money"] > 0.4):
        bonus += 0.06

    return min(bonus, 0.15)  # Cap total synergy bonus


def _identify_top_lens(scores: Dict[str, float]) -> Optional[str]:
    """Identify which lens is driving the conviction."""
    if not scores:
        return None
    top = max(scores, key=scores.get)
    if scores[top] < LENS_ACTIVE_THRESHOLD:
        return None
    labels = {
        "binary_catalyst": "Binary Catalyst",
        "earnings_inflection": "Earnings Inflection",
        "demand_rider": "Demand Rider",
        "float_mechanics": "Float Mechanics",
        "smart_money": "Smart Money",
    }
    return labels.get(top, top)


def _generate_screening_notes(
    scores: Dict[str, float],
    tier: str,
    active: int,
) -> str:
    """Generate human-readable screening notes."""
    parts = []

    # Note strong lenses
    lens_labels = {
        "binary_catalyst": "catalyst",
        "earnings_inflection": "earnings",
        "demand_rider": "demand",
        "float_mechanics": "float",
        "smart_money": "smart_money",
    }
    strong = [lens_labels[k] for k, v in scores.items() if v >= 0.6]
    weak = [lens_labels[k] for k, v in scores.items() if v < 0.15]

    if strong:
        parts.append(f"strong: {','.join(strong)}")
    if weak:
        parts.append(f"weak: {','.join(weak)}")

    # Pattern detection
    if scores.get("binary_catalyst", 0) > 0.5 and scores.get("float_mechanics", 0) > 0.5:
        parts.append("SPRB-pattern")
    if scores.get("earnings_inflection", 0) > 0.5 and scores.get("demand_rider", 0) > 0.5:
        parts.append("SNDK-pattern")

    parts.append(f"{active}/5 lenses active")
    return "; ".join(parts)


def compute_1000x_score(
    catalyst_score: float = 0.0,
    earnings_score: float = 0.0,
    demand_score: float = 0.0,
    float_score: float = 0.0,
    smart_money_score: float = 0.0,
) -> Dict[str, Any]:
    """
    Master scoring function. Combines all five lenses.

    Returns:
        composite_score (0.0 – 1.0)
        conviction_tier (CONVICTION/HIGH/WATCH/SPECULATIVE/PASS)
        active_lenses (0-5)
        top_lens
        screening_notes
        component breakdown
    """
    scores = {
        "binary_catalyst": catalyst_score,
        "earnings_inflection": earnings_score,
        "demand_rider": demand_score,
        "float_mechanics": float_score,
        "smart_money": smart_money_score,
    }

    # Weighted base score
    base = sum(scores[k] * LENS_WEIGHTS[k] for k in scores)

    # Convergence and synergy bonuses
    conv_bonus = _convergence_bonus(scores)
    syn_bonus = _synergy_bonus(scores)

    composite = base + conv_bonus + syn_bonus
    composite = round(min(max(composite, 0.0), 1.0), 4)

    # Assign tier
    if composite > 0.75:
        tier = "CONVICTION"
    elif composite > 0.55:
        tier = "HIGH"
    elif composite > 0.35:
        tier = "WATCH"
    elif composite > 0.15:
        tier = "SPECULATIVE"
    else:
        tier = "PASS"

    active = _count_active_lenses(scores)
    top_lens = _identify_top_lens(scores)
    notes = _generate_screening_notes(scores, tier, active)

    return {
        "composite_score": composite,
        "conviction_tier": tier,
        "active_lenses": active,
        "top_lens": top_lens,
        "screening_notes": notes,
        "components": scores,
        "weights": LENS_WEIGHTS,
        "bonuses": {
            "convergence": conv_bonus,
            "synergy": syn_bonus,
        },
    }
