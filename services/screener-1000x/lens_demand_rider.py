"""
Lens 3 — Structural Demand Rider
==================================
Small companies positioned on megatrend tailwinds (AI, defense, energy
transition, reshoring, biotech) before institutions pile in.

Cross-references NLP megatrend themes with small-cap SEC filings.
The 1000x thesis: small company + big trend + no coverage = explosive re-rating
when institutions discover it.

Data sources:
  - Existing themes table (NLP engine output)
  - SEC EDGAR filings (10-K/10-Q text for megatrend keywords)
  - Entity metadata (sector, subsector, market cap)
"""
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ── Megatrend Definitions ──────────────────────────────────
MEGATRENDS = {
    "ai_ml": {
        "label": "AI / Machine Learning",
        "keywords": [
            "artificial intelligence", "machine learning", "deep learning",
            "large language model", "neural network", "generative ai",
            "computer vision", "natural language processing", "ai inference",
            "gpu computing", "ai accelerator", "transformer model",
            "foundation model", "autonomous", "robotics",
        ],
        "sectors": ["technology", "software", "semiconductors", "cloud"],
        "weight": 1.0,  # Hottest trend
    },
    "defense_security": {
        "label": "Defense & National Security",
        "keywords": [
            "defense contract", "department of defense", "dod",
            "national security", "cybersecurity", "electronic warfare",
            "unmanned", "drone", "uas", "uav", "missile defense",
            "space force", "intelligence community", "classified",
            "hypersonic", "directed energy", "c4isr",
        ],
        "sectors": ["defense", "aerospace", "cybersecurity"],
        "weight": 0.90,
    },
    "energy_transition": {
        "label": "Energy Transition",
        "keywords": [
            "renewable energy", "solar", "wind power", "battery",
            "energy storage", "ev charging", "electric vehicle",
            "hydrogen fuel", "carbon capture", "grid modernization",
            "smart grid", "nuclear", "small modular reactor",
            "clean energy", "decarbonization",
        ],
        "sectors": ["energy", "cleantech", "utilities"],
        "weight": 0.85,
    },
    "reshoring": {
        "label": "Reshoring & Supply Chain",
        "keywords": [
            "reshoring", "onshoring", "nearshoring", "domestic manufacturing",
            "supply chain resilience", "chips act", "ira", "made in america",
            "critical minerals", "rare earth", "semiconductor fab",
            "advanced packaging", "domestic production",
        ],
        "sectors": ["manufacturing", "semiconductors", "materials"],
        "weight": 0.80,
    },
    "biotech_genomics": {
        "label": "Biotech & Genomics",
        "keywords": [
            "gene therapy", "cell therapy", "crispr", "mrna",
            "precision medicine", "genomics", "proteomics",
            "immuno-oncology", "car-t", "antibody drug conjugate",
            "bispecific", "radiopharmaceutical", "glp-1",
        ],
        "sectors": ["biotech", "pharma", "healthcare"],
        "weight": 0.85,
    },
}


def _match_megatrend_keywords(text: str) -> Dict[str, float]:
    """
    Score text against each megatrend's keyword set.
    Returns dict of {trend_name: relevance_score}.
    """
    text_lower = text.lower()
    results = {}

    for trend_name, trend_def in MEGATRENDS.items():
        matched = [kw for kw in trend_def["keywords"] if kw in text_lower]
        if matched:
            # Score: weighted by number of unique matches, capped at 1.0
            density = len(matched) / len(trend_def["keywords"])
            relevance = min(density * 3.0, 1.0)  # 33% keyword match = max
            results[trend_name] = round(relevance * trend_def["weight"], 4)

    return results


def _score_institutional_neglect(
    market_cap: Optional[float],
    signal_count_13f: int,
    entity_type: str,
) -> float:
    """
    How invisible is this company to institutions?
    Low 13F coverage + small cap = maximally neglected.
    """
    if entity_type != "public":
        return 0.8  # Private companies are inherently neglected

    # Market cap factor: smaller = more neglected
    mcap_factor = 0.0
    if market_cap is not None:
        mc_m = market_cap / 1e6
        if mc_m < 100:
            mcap_factor = 1.0
        elif mc_m < 300:
            mcap_factor = 0.8
        elif mc_m < 1000:
            mcap_factor = 0.5
        elif mc_m < 5000:
            mcap_factor = 0.2
        else:
            mcap_factor = 0.0

    # 13F coverage factor: fewer holders = more neglected
    coverage_factor = 0.0
    if signal_count_13f == 0:
        coverage_factor = 1.0
    elif signal_count_13f <= 3:
        coverage_factor = 0.8
    elif signal_count_13f <= 10:
        coverage_factor = 0.5
    elif signal_count_13f <= 25:
        coverage_factor = 0.2
    else:
        coverage_factor = 0.05

    return round(0.5 * mcap_factor + 0.5 * coverage_factor, 4)


# Megatrends that the hyperscaler-capex macro signal applies to. A capex
# inflection lifts the entire AI-infrastructure supply chain, so it amplifies
# demand for names whose strongest trend is AI/ML.
_CAPEX_CONTEXT_TRENDS = {"ai_ml"}
_MAX_CONTEXT_BOOST = 0.20


def _context_demand_boost(
    best_trend: str,
    market_context: Optional[List[Dict[str, Any]]],
) -> float:
    """Sprint 11.3: lift L1 demand when hyperscaler capex is inflecting.

    `market_context` is the set of active market-wide context signals (from the
    `market_context_signals` table). When a `hyperscaler_capex_inflection` is
    active and this candidate's strongest megatrend is AI/ML, the whole AI-infra
    lane gets a modest, bounded boost scaled by the YoY magnitude.
    """
    if not market_context or best_trend not in _CAPEX_CONTEXT_TRENDS:
        return 0.0
    for ctx in market_context:
        if ctx.get("context_type") != "hyperscaler_capex_inflection":
            continue
        if not ctx.get("is_active", True):
            continue
        magnitude = ctx.get("value") or 0.0
        # 0.10 floor for any active inflection, +0.10 scaled by YoY (capped).
        return round(min(_MAX_CONTEXT_BOOST, 0.10 + 0.10 * min(magnitude, 1.0)), 4)
    return 0.0


def _score_sector_alignment(sector: Optional[str], megatrend: str) -> float:
    """Check if company's sector aligns with the megatrend."""
    if not sector:
        return 0.3  # Unknown sector — partial credit
    trend_def = MEGATRENDS.get(megatrend, {})
    trend_sectors = trend_def.get("sectors", [])
    sector_lower = sector.lower()
    for ts in trend_sectors:
        if ts in sector_lower:
            return 1.0
    return 0.2  # Sector doesn't align — possible but unlikely


def score_demand_rider(
    signals: List[Dict[str, Any]],
    entity_type: str = "public",
    sector: Optional[str] = None,
    market_cap: Optional[float] = None,
    themes: Optional[List[Dict[str, Any]]] = None,
    filing_text: Optional[str] = None,
    market_context: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Compute Lens 3 score for structural demand alignment.

    Args:
        market_context: active market-wide context signals (Sprint 11.3). A
            hyperscaler capex inflection amplifies AI/ML-aligned demand.

    Returns:
        demand_score (0.0-1.0)
        megatrend_alignment (strongest trend)
        theme_strength
        institutional_neglect
        demand_details
    """
    # Gather text from signals, themes, and filings
    all_text = ""
    for sig in signals:
        all_text += " " + (sig.get("notes") or "")
        raw = sig.get("raw_data") or {}
        all_text += " " + str(raw)

    if themes:
        for theme in themes:
            all_text += " " + (theme.get("label") or "")
            all_text += " " + (theme.get("description") or "")

    if filing_text:
        all_text += " " + filing_text

    # Match megatrends
    trend_scores = _match_megatrend_keywords(all_text)

    if not trend_scores:
        return {
            "demand_score": 0.0,
            "megatrend_alignment": None,
            "theme_strength": None,
            "institutional_neglect": None,
            "demand_details": {"reason": "no_megatrend_alignment"},
        }

    # Best megatrend
    best_trend = max(trend_scores, key=trend_scores.get)
    theme_strength = trend_scores[best_trend]

    # Sector alignment
    sector_align = _score_sector_alignment(sector, best_trend)

    # Institutional neglect
    signal_count_13f = sum(1 for s in signals if s.get("signal_type") == "sec_13f")
    neglect = _score_institutional_neglect(market_cap, signal_count_13f, entity_type)

    # Composite: 35% theme strength, 25% neglect, 25% sector alignment, 15% trend weight
    trend_weight = MEGATRENDS.get(best_trend, {}).get("weight", 0.5)
    composite = (
        0.35 * theme_strength +
        0.25 * neglect +
        0.25 * sector_align +
        0.15 * trend_weight
    )

    # S11.3: hyperscaler capex inflection lifts the whole AI-infra lane.
    context_boost = _context_demand_boost(best_trend, market_context)
    composite = round(min(max(composite + context_boost, 0.0), 1.0), 4)

    cited_ids = [s.get("signal_id") for s in signals if s.get("signal_id")]

    return {
        "demand_score": composite,
        "megatrend_alignment": MEGATRENDS.get(best_trend, {}).get("label", best_trend),
        "theme_strength": theme_strength,
        "institutional_neglect": neglect,
        "cited_signal_ids": cited_ids,
        "demand_details": {
            "components": {
                "theme_strength": theme_strength,
                "institutional_neglect": neglect,
                "sector_alignment": sector_align,
                "trend_weight": trend_weight,
                "context_boost": context_boost,
            },
            "all_trends": trend_scores,
            "best_trend_id": best_trend,
            "cited_signal_ids": cited_ids,
        },
    }
