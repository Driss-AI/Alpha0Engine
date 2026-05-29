"""
Illiquidity Risk Scorer
=======================
Evaluates whether a company is at risk of running out of capital
in a frozen IPO market. Key factors:

1. Runway Risk      — estimated months of cash remaining
2. Funding Staleness — time since last funding round
3. Market Freeze     — secondary market discount as proxy for IPO window
4. Burn Acceleration — increasing burn rate signals
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def score_runway_risk(estimated_runway: Optional[float]) -> float:
    """
    Runway risk (0.0 = safe, 1.0 = critical).
    <6 months = critical, 6-12 = danger, 12-18 = caution, 18+ = safe.
    """
    if estimated_runway is None:
        return 0.5  # Unknown = moderate risk
    if estimated_runway < 3:
        return 1.0
    if estimated_runway < 6:
        return 0.85
    if estimated_runway < 12:
        return 0.6
    if estimated_runway < 18:
        return 0.35
    if estimated_runway < 24:
        return 0.15
    return 0.05


def score_funding_staleness(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    How long since the last funding event?
    >24 months without funding = growing concern.
    """
    form_d_signals = sorted(
        [s for s in signals if s.get("signal_type") == "form_d"],
        key=lambda s: s.get("signal_date", ""),
        reverse=True,
    )
    if not form_d_signals:
        return {"stale_months": None, "score": 0.5}

    latest_date = form_d_signals[0].get("signal_date")
    if isinstance(latest_date, str):
        try:
            latest_date = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
        except ValueError:
            return {"stale_months": None, "score": 0.5}
    elif not isinstance(latest_date, datetime):
        return {"stale_months": None, "score": 0.5}

    months_since = (datetime.utcnow() - latest_date.replace(tzinfo=None)).days / 30

    if months_since > 36:
        score = 0.95
    elif months_since > 24:
        score = 0.75
    elif months_since > 18:
        score = 0.5
    elif months_since > 12:
        score = 0.3
    else:
        score = 0.1

    return {"stale_months": round(months_since, 1), "score": round(score, 4)}


def score_market_freeze_exposure(signals: List[Dict[str, Any]]) -> float:
    """
    Secondary market discount as proxy for IPO market conditions.
    Deep discounts on secondary = frozen market = higher risk.
    """
    secondary_signals = [s for s in signals if s.get("signal_type") == "secondary_trade"]
    if not secondary_signals:
        return 0.3  # No data = moderate default

    # Use signal values (negative = discount)
    values = [s.get("value", 0) for s in secondary_signals if s.get("value") is not None]
    if not values:
        return 0.3

    avg_value = sum(values) / len(values)

    # Negative value = discount = frozen market
    if avg_value < -0.3:
        return 0.9
    if avg_value < -0.15:
        return 0.7
    if avg_value < 0:
        return 0.5
    if avg_value < 0.1:
        return 0.3
    return 0.1  # Premium = healthy market


def score_signal_concentration(signals: List[Dict[str, Any]]) -> float:
    """
    Risk from over-reliance on a single signal source.
    Diversified signal sources = lower risk.
    """
    if not signals:
        return 0.5

    source_counts = {}
    for s in signals:
        src = s.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    if len(source_counts) <= 1:
        return 0.9  # Single source = high risk
    if len(source_counts) == 2:
        return 0.6

    # Check if one source dominates (>70% of signals)
    total = len(signals)
    max_share = max(source_counts.values()) / total
    if max_share > 0.7:
        return 0.7
    if max_share > 0.5:
        return 0.4
    return 0.15  # Well diversified


def compute_illiquidity_risk(
    signals: List[Dict[str, Any]],
    estimated_runway: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Full illiquidity risk assessment.
    """
    runway = score_runway_risk(estimated_runway)
    staleness = score_funding_staleness(signals)
    market_freeze = score_market_freeze_exposure(signals)
    concentration = score_signal_concentration(signals)

    # Weighted composite
    illiquidity = (
        runway * 0.35 +
        staleness["score"] * 0.25 +
        market_freeze * 0.25 +
        concentration * 0.15
    )
    illiquidity = round(min(max(illiquidity, 0.0), 1.0), 4)

    is_flagged = illiquidity > 0.6

    flags = []
    if runway > 0.7:
        flags.append("RUNWAY_CRITICAL")
    if staleness["score"] > 0.7:
        flags.append("STALE_FUNDING")
    if market_freeze > 0.7:
        flags.append("MARKET_FROZEN")
    if concentration > 0.7:
        flags.append("SINGLE_SOURCE_RISK")

    return {
        "illiquidity_score": illiquidity,
        "runway_risk": runway,
        "funding_stale_months": staleness["stale_months"],
        "market_freeze_exposure": market_freeze,
        "signal_concentration": concentration,
        "illiquidity_flag": is_flagged,
        "flags": flags,
    }
