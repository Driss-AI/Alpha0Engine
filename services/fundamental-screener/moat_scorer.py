"""
Moat Scorer
===========
Computes competitive-moat strength from accumulated signals.
Five pillars → weighted composite moat_score (0.0 – 1.0).

Pillars:
  1. Patent Strength    — patent count, grant rate, citation velocity
  2. IP Breadth         — unique CPC classes, patent family diversity
  3. Talent Density     — job postings quality, key hires (CFO/GC)
  4. GitHub Momentum    — stars, commits, contributor growth
  5. Competitive Position — sector signal density vs peers
"""
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Weights for composite moat score
MOAT_WEIGHTS = {
    "patent_strength": 0.25,
    "ip_breadth": 0.15,
    "talent_density": 0.20,
    "github_momentum": 0.20,
    "competitive_position": 0.20,
}


def _sigmoid_normalize(value: float, midpoint: float, steepness: float = 1.0) -> float:
    """Map raw count to 0-1 via logistic curve. midpoint = value that gives 0.5."""
    import math
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))
    except OverflowError:
        return 0.0 if value < midpoint else 1.0


def score_patent_strength(signals: List[Dict[str, Any]]) -> float:
    """
    Patent strength from filing/grant signals.
    Factors: total patents, grant rate, recency.
    """
    patent_signals = [s for s in signals if s.get("signal_type") in ("patent_filing", "patent_grant")]
    if not patent_signals:
        return 0.0

    total = len(patent_signals)
    grants = len([s for s in patent_signals if s.get("signal_type") == "patent_grant"])
    grant_rate = grants / max(total, 1)

    # Recency bonus: patents in last 12 months count 2x
    cutoff = datetime.utcnow() - timedelta(days=365)
    recent = len([s for s in patent_signals
                  if isinstance(s.get("signal_date"), str) and s["signal_date"] > cutoff.isoformat()
                  or isinstance(s.get("signal_date"), datetime) and s["signal_date"] > cutoff])
    recency_bonus = min(recent / max(total, 1), 1.0) * 0.2

    raw = _sigmoid_normalize(total, midpoint=10, steepness=0.3)
    return min(raw * (0.6 + 0.4 * grant_rate) + recency_bonus, 1.0)


def score_ip_breadth(signals: List[Dict[str, Any]]) -> float:
    """
    IP breadth from patent CPC/IPC class diversity.
    More unique classes = broader IP moat.
    """
    cpc_classes = set()
    for s in signals:
        if s.get("signal_type") in ("patent_filing", "patent_grant"):
            raw = s.get("raw_data", {})
            if isinstance(raw, dict):
                for cls in raw.get("cpc_classes", []):
                    cpc_classes.add(cls[:4] if len(cls) >= 4 else cls)
                if raw.get("cpc_section"):
                    cpc_classes.add(raw["cpc_section"])
    if not cpc_classes:
        return 0.0
    return _sigmoid_normalize(len(cpc_classes), midpoint=5, steepness=0.5)


def score_talent_density(signals: List[Dict[str, Any]]) -> float:
    """
    Talent density from job postings and key executive hires.
    High-value hires (CFO, GC, VP Eng) get 3x weight.
    """
    job_signals = [s for s in signals if s.get("signal_type") == "job_posting"]
    if not job_signals:
        return 0.0

    total = len(job_signals)
    key_hires = 0
    KEY_TITLES = ["cfo", "chief financial", "general counsel", "vp eng", "vp of eng",
                  "head of engineering", "chief technology", "cto", "chief revenue"]

    for s in job_signals:
        notes = (s.get("notes") or "").lower()
        raw = s.get("raw_data", {})
        title = (raw.get("title") or "").lower() if isinstance(raw, dict) else ""
        if any(kt in notes or kt in title for kt in KEY_TITLES):
            key_hires += 1

    base = _sigmoid_normalize(total, midpoint=20, steepness=0.15)
    hire_bonus = min(key_hires * 0.15, 0.3)
    return min(base + hire_bonus, 1.0)


def score_github_momentum(signals: List[Dict[str, Any]]) -> float:
    """
    GitHub momentum from stars, commits, contributor growth.
    """
    gh_signals = [s for s in signals if s.get("signal_type") in ("github_commit", "github_star")]
    if not gh_signals:
        return 0.0

    stars = len([s for s in gh_signals if s.get("signal_type") == "github_star"])
    commits = len([s for s in gh_signals if s.get("signal_type") == "github_commit"])

    # Recent activity weighted more
    cutoff = datetime.utcnow() - timedelta(days=90)
    recent = len([s for s in gh_signals
                  if isinstance(s.get("signal_date"), str) and s["signal_date"] > cutoff.isoformat()
                  or isinstance(s.get("signal_date"), datetime) and s["signal_date"] > cutoff])

    star_score = _sigmoid_normalize(stars, midpoint=50, steepness=0.05)
    commit_score = _sigmoid_normalize(commits, midpoint=100, steepness=0.02)
    recency = min(recent / max(len(gh_signals), 1), 1.0)

    return star_score * 0.4 + commit_score * 0.4 + recency * 0.2


def score_competitive_position(signals: List[Dict[str, Any]], sector_avg_signals: float) -> float:
    """
    Competitive positioning relative to sector peers.
    Entity with more signals than sector average = stronger position.
    """
    if sector_avg_signals <= 0:
        return 0.5  # No data = neutral
    ratio = len(signals) / sector_avg_signals
    return min(_sigmoid_normalize(ratio, midpoint=1.0, steepness=2.0), 1.0)


def compute_moat_score(signals: List[Dict[str, Any]], sector_avg_signals: float = 10.0) -> Dict[str, float]:
    """
    Master moat scorer — returns all pillar scores + composite.
    """
    pillars = {
        "patent_strength": score_patent_strength(signals),
        "ip_breadth": score_ip_breadth(signals),
        "talent_density": score_talent_density(signals),
        "github_momentum": score_github_momentum(signals),
        "competitive_position": score_competitive_position(signals, sector_avg_signals),
    }

    composite = sum(pillars[k] * MOAT_WEIGHTS[k] for k in pillars)
    pillars["moat_score"] = round(composite, 4)

    logger.info(f"Moat score computed: {composite:.3f} | pillars={pillars}")
    return pillars
