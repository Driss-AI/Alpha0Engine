"""
Hype vs Reality Detector
========================
Identifies vaporware: companies with high buzz but poor fundamentals.

Hype signals (inflate score):
  - News mentions without substance
  - High NLP sentiment scores
  - Social media / GitHub stars without commits
  - Large Form D raises with no patent/product signals

Substance signals (deflate score):
  - Patent filings and grants
  - Consistent GitHub commits (not just stars)
  - Key executive hires (CFO, GC = IPO prep)
  - Revenue signals / 10-K data
  - Crossover fund investment (smart money validation)
"""
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Signal types that indicate hype
HYPE_SIGNALS = {"news_mention", "github_star"}
# Signal types that indicate substance
SUBSTANCE_SIGNALS = {"patent_filing", "patent_grant", "github_commit", "job_posting", "crossover_filing"}
# Neutral signals
NEUTRAL_SIGNALS = {"form_d", "secondary_trade", "citation"}


def compute_hype_score(signals: List[Dict[str, Any]]) -> float:
    """
    Hype score (0.0 – 1.0). High = lots of buzz signals.
    """
    if not signals:
        return 0.0
    hype_count = sum(1 for s in signals if s.get("signal_type") in HYPE_SIGNALS)
    total = len(signals)
    raw_ratio = hype_count / total

    # Weight recent hype more heavily
    cutoff = datetime.utcnow() - timedelta(days=90)
    recent_hype = sum(1 for s in signals
                      if s.get("signal_type") in HYPE_SIGNALS
                      and _is_recent(s, cutoff))
    recent_total = sum(1 for s in signals if _is_recent(s, cutoff))
    recent_ratio = recent_hype / max(recent_total, 1)

    # Combine: 40% overall ratio + 60% recent ratio
    return round(min(raw_ratio * 0.4 + recent_ratio * 0.6, 1.0), 4)


def compute_substance_score(signals: List[Dict[str, Any]]) -> float:
    """
    Substance score (0.0 – 1.0). High = real product/IP/team building.
    """
    if not signals:
        return 0.0

    substance_count = sum(1 for s in signals if s.get("signal_type") in SUBSTANCE_SIGNALS)
    total = len(signals)
    raw_ratio = substance_count / total

    # Bonus for diversity of substance signals
    substance_types = set(s.get("signal_type") for s in signals if s.get("signal_type") in SUBSTANCE_SIGNALS)
    diversity_bonus = min(len(substance_types) * 0.1, 0.3)

    # Bonus for crossover fund validation (smart money = strong signal)
    crossover = sum(1 for s in signals if s.get("signal_type") == "crossover_filing")
    crossover_bonus = min(crossover * 0.1, 0.2)

    return round(min(raw_ratio + diversity_bonus + crossover_bonus, 1.0), 4)


def compute_hype_gap(hype: float, substance: float) -> float:
    """
    Hype gap = hype - substance.
    >0.3 = warning (more sizzle than steak)
    >0.5 = red flag (vaporware territory)
    <0   = healthy (more substance than hype)
    """
    return round(hype - substance, 4)


def detect_hype_patterns(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Full hype detection with pattern analysis.
    """
    hype = compute_hype_score(signals)
    substance = compute_substance_score(signals)
    gap = compute_hype_gap(hype, substance)

    # Flag detection
    is_flagged = gap > 0.3

    # Pattern details
    patterns = []
    if gap > 0.5:
        patterns.append("VAPORWARE_RISK: Extremely high hype with minimal substance")
    elif gap > 0.3:
        patterns.append("HYPE_WARNING: Buzz outpacing product signals")

    # Stars without commits
    stars = sum(1 for s in signals if s.get("signal_type") == "github_star")
    commits = sum(1 for s in signals if s.get("signal_type") == "github_commit")
    if stars > 10 and commits == 0:
        patterns.append("GHOST_REPO: GitHub stars with zero commits")
        is_flagged = True

    # Big raise but no patents/hires
    form_ds = [s for s in signals if s.get("signal_type") == "form_d"]
    patents = sum(1 for s in signals if s.get("signal_type") in ("patent_filing", "patent_grant"))
    hires = sum(1 for s in signals if s.get("signal_type") == "job_posting")
    if len(form_ds) > 0 and patents == 0 and hires == 0:
        patterns.append("FUNDRAISE_ONLY: Capital raised with no visible IP or team building")

    # News without substance
    news = sum(1 for s in signals if s.get("signal_type") == "news_mention")
    if news > 5 and substance < 0.2:
        patterns.append("MEDIA_INFLATED: Heavy media coverage with thin fundamentals")

    return {
        "hype_score": hype,
        "substance_score": substance,
        "hype_gap": gap,
        "hype_flag": is_flagged,
        "patterns": patterns,
    }


def _is_recent(signal: Dict[str, Any], cutoff: datetime) -> bool:
    sd = signal.get("signal_date")
    if isinstance(sd, str):
        return sd > cutoff.isoformat()
    if isinstance(sd, datetime):
        return sd > cutoff
    return False
