"""
Lens 2 — Earnings Inflection (SNDK Pattern)
=============================================
Identifies companies at the inflection point from loss to profit,
with accelerating revenue and expanding margins. The SNDK archetype:
years of losses → sudden profitability → massive re-rating.

Tracks EPS trajectory over 4-8 quarters via SEC XBRL data.
Key signal: consecutive improving EPS quarters approaching zero crossing.

Data sources:
  - SEC EDGAR XBRL (quarterly EPS, revenue, margins)
"""
import os
import logging
import httpx
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}


def _extract_quarterly_series(facts: Dict, taxonomy: str, concept: str, n: int = 12) -> List[Dict]:
    """Extract last N quarterly values for trend analysis."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
        values = units.get("USD", units.get("USD/shares", next(iter(units.values()), [])))
        quarterly = [v for v in values if v.get("form") in ("10-Q", "10-Q/A")]
        quarterly.sort(key=lambda x: x.get("end", ""))
        return quarterly[-n:]
    except (KeyError, IndexError, TypeError):
        return []


def _extract_eps_series(facts: Dict, n: int = 12) -> List[Dict]:
    """Extract EPS (earnings per share) quarterly series."""
    # Try multiple XBRL concepts for EPS
    for concept in [
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
        "IncomeLossFromContinuingOperationsPerBasicShare",
    ]:
        series = _extract_quarterly_series(facts, "us-gaap", concept, n)
        if len(series) >= 3:
            return series
    return []


def _compute_trajectory(values: List[float]) -> str:
    """Classify EPS trajectory pattern."""
    if len(values) < 3:
        return "insufficient_data"

    recent_3 = values[-3:]
    all_positive = all(v > 0 for v in recent_3)
    all_negative = all(v < 0 for v in recent_3)
    improving = all(recent_3[i] > recent_3[i-1] for i in range(1, len(recent_3)))

    # Check for zero crossing (inflection)
    has_crossing = False
    for i in range(1, len(values)):
        if values[i-1] < 0 and values[i] >= 0:
            has_crossing = True
            break

    if has_crossing and all_positive:
        return "inflected_positive"
    if improving and recent_3[-1] > 0 and recent_3[0] < 0:
        return "inflecting"
    if improving and all_negative:
        return "accelerating_losses_shrinking"
    if all_positive and improving:
        return "accelerating"
    if all_negative and not improving:
        return "declining"
    if improving:
        return "improving"
    return "mixed"


def _score_eps_trajectory(trajectory: str, eps_values: List[float]) -> float:
    """Score based on EPS trajectory pattern."""
    scores = {
        "inflecting": 1.0,          # SNDK pattern — at the crossing
        "inflected_positive": 0.90,  # Just crossed — early re-rating
        "accelerating_losses_shrinking": 0.70,  # Approaching zero
        "accelerating": 0.50,       # Already profitable, accelerating
        "improving": 0.40,
        "mixed": 0.15,
        "declining": 0.05,
        "insufficient_data": 0.0,
    }
    base = scores.get(trajectory, 0.0)

    # Bonus: if losses are shrinking toward zero, closer = better
    if eps_values and eps_values[-1] < 0:
        # How close to zero? Scale: -0.01 = very close, -5.0 = far
        closeness = max(0, 1.0 - abs(eps_values[-1]) / 2.0)
        base = max(base, base + closeness * 0.2)

    return min(base, 1.0)


def _score_revenue_acceleration(rev_values: List[float]) -> tuple:
    """Detect revenue growth acceleration (growth rate is itself growing)."""
    if len(rev_values) < 4:
        return 0.0, None

    # Compute sequential growth rates
    growths = []
    for i in range(1, len(rev_values)):
        if rev_values[i-1] > 0:
            growths.append((rev_values[i] - rev_values[i-1]) / rev_values[i-1])

    if len(growths) < 2:
        return 0.0, None

    # Check if growth rate is itself accelerating
    recent_growth = growths[-1]
    prior_growth = growths[-2] if len(growths) >= 2 else 0
    acceleration = recent_growth - prior_growth

    if acceleration > 0.10:
        score = 1.0
    elif acceleration > 0.05:
        score = 0.80
    elif acceleration > 0.02:
        score = 0.60
    elif acceleration > 0:
        score = 0.40
    elif acceleration > -0.02:
        score = 0.20
    else:
        score = 0.05

    return score, round(acceleration, 4)


def _score_margin_expansion(gp_values: List[float], rev_values: List[float]) -> tuple:
    """Track gross margin expansion over quarters."""
    if len(gp_values) < 2 or len(rev_values) < 2:
        return 0.0, None

    n = min(len(gp_values), len(rev_values))
    margins = []
    for i in range(n):
        if rev_values[i] > 0:
            margins.append(gp_values[i] / rev_values[i])

    if len(margins) < 2:
        return 0.0, None

    # Average margin expansion per quarter
    expansions = [margins[i] - margins[i-1] for i in range(1, len(margins))]
    avg_expansion = sum(expansions) / len(expansions)

    if avg_expansion > 0.03:
        score = 1.0
    elif avg_expansion > 0.01:
        score = 0.75
    elif avg_expansion > 0:
        score = 0.50
    elif avg_expansion > -0.01:
        score = 0.25
    else:
        score = 0.05

    return score, round(avg_expansion, 4)


def _quarters_until_profit(eps_values: List[float]) -> Optional[int]:
    """Estimate how many quarters until profitability based on trajectory."""
    if not eps_values or eps_values[-1] >= 0:
        return 0  # Already profitable

    # Linear extrapolation from last 4 points
    recent = eps_values[-4:] if len(eps_values) >= 4 else eps_values
    if len(recent) < 2:
        return None

    # Average improvement per quarter
    improvements = [recent[i] - recent[i-1] for i in range(1, len(recent))]
    avg_improvement = sum(improvements) / len(improvements)

    if avg_improvement <= 0:
        return None  # Not improving

    quarters = int(-recent[-1] / avg_improvement) + 1
    return min(quarters, 20)  # Cap at 5 years


async def fetch_company_facts(cik: str) -> Optional[Dict]:
    """Pull XBRL data from SEC EDGAR."""
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error(f"SEC fetch failed for CIK {cik}: {e}")
            return None


async def score_earnings_inflection(
    cik: str,
    facts: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Compute Lens 2 score for earnings inflection.

    Returns:
        earnings_score (0.0-1.0)
        eps_trajectory
        quarters_to_profit
        revenue_acceleration
        margin_expansion_rate
        earnings_details
    """
    if facts is None:
        facts = await fetch_company_facts(cik)
    if not facts:
        return {
            "earnings_score": 0.0,
            "eps_trajectory": "no_data",
            "quarters_to_profit": None,
            "revenue_acceleration": None,
            "margin_expansion_rate": None,
            "earnings_details": {"error": "no_xbrl_data"},
        }

    # Extract quarterly series
    eps_raw = _extract_eps_series(facts, n=12)
    eps_values = [float(v["val"]) for v in eps_raw] if eps_raw else []

    rev_raw = _extract_quarterly_series(facts, "us-gaap", "Revenues", n=12)
    if not rev_raw:
        rev_raw = _extract_quarterly_series(
            facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", n=12
        )
    rev_values = [float(v["val"]) for v in rev_raw] if rev_raw else []

    gp_raw = _extract_quarterly_series(facts, "us-gaap", "GrossProfit", n=12)
    gp_values = [float(v["val"]) for v in gp_raw] if gp_raw else []

    # Score each dimension
    trajectory = _compute_trajectory(eps_values)
    eps_score = _score_eps_trajectory(trajectory, eps_values)
    rev_accel_score, rev_acceleration = _score_revenue_acceleration(rev_values)
    margin_score, margin_rate = _score_margin_expansion(gp_values, rev_values)
    qtrs_to_profit = _quarters_until_profit(eps_values)

    # Quarters proximity bonus: closer to profitability = higher score
    proximity_bonus = 0.0
    if qtrs_to_profit is not None and qtrs_to_profit > 0:
        if qtrs_to_profit <= 2:
            proximity_bonus = 0.15
        elif qtrs_to_profit <= 4:
            proximity_bonus = 0.08

    # Composite: 40% EPS trajectory, 30% revenue acceleration, 20% margin, 10% proximity
    composite = (
        0.40 * eps_score +
        0.30 * rev_accel_score +
        0.20 * margin_score +
        0.10 * min(proximity_bonus * 5, 1.0)
    )
    composite = round(min(max(composite, 0.0), 1.0), 4)

    return {
        "earnings_score": composite,
        "eps_trajectory": trajectory,
        "quarters_to_profit": qtrs_to_profit,
        "revenue_acceleration": rev_acceleration,
        "margin_expansion_rate": margin_rate,
        "earnings_details": {
            "components": {
                "eps_trajectory": eps_score,
                "revenue_acceleration": rev_accel_score,
                "margin_expansion": margin_score,
                "proximity_bonus": proximity_bonus,
            },
            "eps_values": eps_values[-8:],
            "rev_values_count": len(rev_values),
            "data_quarters": len(eps_values),
        },
    }
