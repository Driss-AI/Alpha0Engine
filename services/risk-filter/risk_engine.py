"""
Risk Filter Engine
==================
Combines hype detection + illiquidity risk into composite risk score.

Risk Tiers:
  GREEN  (0.0 – 0.25): Low risk — proceed with confidence
  YELLOW (0.25 – 0.45): Moderate risk — monitor closely
  ORANGE (0.45 – 0.65): Elevated risk — proceed with caution
  RED    (0.65 – 1.0):  High risk — avoid or deep-dive required
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Weights for composite risk
RISK_WEIGHTS = {
    "hype_gap": 0.30,
    "illiquidity": 0.35,
    "concentration": 0.15,
    "sector_crowding": 0.20,
}


def score_sector_crowding(entity_signal_count: int, sector_avg: float, sector_entity_count: int) -> float:
    """
    Sector crowding risk. Too many competitors in a hot sector
    dilutes the opportunity for any single company.
    """
    if sector_entity_count < 3:
        return 0.1  # Niche = low crowding

    # High crowding if many entities and signal count is below average
    if sector_entity_count > 20:
        crowding = 0.7
    elif sector_entity_count > 10:
        crowding = 0.5
    elif sector_entity_count > 5:
        crowding = 0.3
    else:
        crowding = 0.15

    # If this entity is below average, it's at more risk of being crowded out
    if sector_avg > 0 and entity_signal_count < sector_avg * 0.5:
        crowding = min(crowding + 0.2, 1.0)

    return round(crowding, 4)


def compute_risk_score(
    hype_result: Dict[str, Any],
    illiquidity_result: Dict[str, Any],
    entity_signal_count: int = 0,
    sector_avg_signals: float = 10.0,
    sector_entity_count: int = 5,
) -> Dict[str, Any]:
    """
    Master risk scoring. Combines all risk dimensions.
    """
    hype_gap = max(hype_result.get("hype_gap", 0.0), 0.0)  # Only positive gaps = risk
    hype_gap_normalized = min(hype_gap / 0.6, 1.0)  # 0.6+ gap = max risk

    illiquidity = illiquidity_result.get("illiquidity_score", 0.0)
    concentration = illiquidity_result.get("signal_concentration", 0.0)
    crowding = score_sector_crowding(entity_signal_count, sector_avg_signals, sector_entity_count)

    composite = (
        hype_gap_normalized * RISK_WEIGHTS["hype_gap"] +
        illiquidity * RISK_WEIGHTS["illiquidity"] +
        concentration * RISK_WEIGHTS["concentration"] +
        crowding * RISK_WEIGHTS["sector_crowding"]
    )
    composite = round(min(max(composite, 0.0), 1.0), 4)

    # Assign tier
    if composite < 0.25:
        tier = "GREEN"
    elif composite < 0.45:
        tier = "YELLOW"
    elif composite < 0.65:
        tier = "ORANGE"
    else:
        tier = "RED"

    # Collect all flags
    all_flags = {}
    if hype_result.get("hype_flag"):
        all_flags["hype"] = hype_result.get("patterns", [])
    if illiquidity_result.get("illiquidity_flag"):
        all_flags["illiquidity"] = illiquidity_result.get("flags", [])
    if crowding > 0.6:
        all_flags["crowding"] = ["SECTOR_CROWDED"]

    # Build notes
    notes_parts = []
    if hype_gap_normalized > 0.5:
        notes_parts.append("high hype gap")
    if illiquidity > 0.6:
        notes_parts.append("illiquidity concern")
    if concentration > 0.6:
        notes_parts.append("concentrated signals")
    if crowding > 0.5:
        notes_parts.append("crowded sector")

    return {
        "risk_score": composite,
        "risk_tier": tier,
        "risk_flags": all_flags,
        "risk_notes": "; ".join(notes_parts) if notes_parts else "within limits",
        "components": {
            "hype_gap": hype_gap_normalized,
            "illiquidity": illiquidity,
            "concentration": concentration,
            "sector_crowding": crowding,
        },
    }
