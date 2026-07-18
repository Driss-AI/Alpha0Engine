"""
Lens 1 — Binary Catalyst (SPRB Pattern)
========================================
Identifies micro-cap stocks with upcoming binary catalysts that can
produce overnight 10x-100x moves. The SPRB archetype: <$500M market cap,
FDA approval catalyst, tiny float, cash runway to reach the event.

Score = catalyst_proximity × inverse_market_cap × cash_runway_factor

Data sources:
  - SEC EDGAR XBRL (market cap, cash, burn rate)
  - SEC 8-K/10-K filings (catalyst mentions via NLP)
  - USPTO patent grants (patent catalysts)
  - Existing signals table (crossover_filing, patent_grant, etc.)
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── Catalyst type weights (how binary is the event?) ────────
CATALYST_WEIGHTS = {
    "fda_approval": 1.0,
    "fda_pdufa": 0.95,
    "fda_adcom": 0.85,
    "patent_grant": 0.70,
    "patent_litigation_ruling": 0.80,
    "merger_acquisition": 0.90,
    "contract_award": 0.65,
    "regulatory_approval": 0.75,
    "clinical_trial_data": 0.90,
    "partnership_announcement": 0.50,
}

# ── Market cap tiers for inverse scaling ────────────────────
def _inverse_mcap_score(market_cap: Optional[float]) -> float:
    """Smaller market cap = more explosive potential. <$500M preferred."""
    if market_cap is None:
        return 0.0
    if market_cap <= 0:
        return 0.0
    mc_m = market_cap / 1e6  # in millions
    if mc_m < 50:
        return 1.0     # Nano-cap: maximum asymmetry
    if mc_m < 150:
        return 0.90
    if mc_m < 300:
        return 0.75
    if mc_m < 500:
        return 0.60
    if mc_m < 1000:
        return 0.35    # Small-cap: still possible but less explosive
    if mc_m < 2000:
        return 0.15
    return 0.05         # Mid/large cap: 1000x essentially impossible


def _catalyst_proximity_score(days_until: Optional[int]) -> float:
    """
    Closer catalyst = higher urgency. Sweet spot: 30-90 days.
    Too close (<7 days) = already priced in somewhat.
    Too far (>365 days) = too much uncertainty.
    """
    if days_until is None:
        return 0.0
    if days_until < 0:
        return 0.05     # Catalyst passed — check if it was positive
    if days_until <= 7:
        return 0.60     # Very near — partial pricing
    if days_until <= 30:
        return 1.0      # Optimal window
    if days_until <= 60:
        return 0.90
    if days_until <= 90:
        return 0.80
    if days_until <= 180:
        return 0.50
    if days_until <= 365:
        return 0.25
    return 0.05


def _cash_runway_factor(runway_months: Optional[float]) -> float:
    """Company must survive to reach the catalyst."""
    if runway_months is None:
        return 0.3   # Unknown — penalize but don't zero
    if runway_months > 24:
        return 1.0
    if runway_months > 18:
        return 0.9
    if runway_months > 12:
        return 0.7
    if runway_months > 6:
        return 0.4
    return 0.1       # May not survive to catalyst


def detect_catalysts_from_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract binary catalyst candidates from existing signals.
    Maps signal types to catalyst categories.
    """
    catalyst_map = {
        "patent_grant": "patent_grant",
        "patent_filing": "patent_grant",
        "crossover_filing": "regulatory_approval",
        "form_d": "partnership_announcement",
        "clinical_trial": "clinical_trial_data",
        "fda_catalyst": "fda_approval",
        "8k_event": "regulatory_approval",  # Overridden by keyword detection below
        "sec_13f": None,  # Not a catalyst
        "github_star": None,
        "github_commit": None,
    }

    catalysts = []
    for sig in signals:
        cat_type = catalyst_map.get(sig.get("signal_type"))
        if cat_type is None:
            continue

        # Check for FDA-related keywords in notes
        notes = (sig.get("notes") or "").lower()
        raw = sig.get("raw_data") or {}
        text = notes + " " + str(raw).lower()

        if any(kw in text for kw in ["fda", "pdufa", "nda", "bla", "anda", "510(k)"]):
            cat_type = "fda_approval"
        elif any(kw in text for kw in ["clinical trial", "phase 3", "phase iii", "pivotal"]):
            cat_type = "clinical_trial_data"
        elif any(kw in text for kw in ["merger", "acquisition", "takeover", "buyout"]):
            cat_type = "merger_acquisition"
        elif any(kw in text for kw in ["contract", "award", "dod", "defense"]):
            cat_type = "contract_award"

        # Use real catalyst_proximity_days from CT.gov data if available
        days_until = raw.get("catalyst_proximity_days")

        # Fallback: estimate from signal date
        if days_until is None:
            sig_date = sig.get("signal_date")
            if sig_date:
                try:
                    if isinstance(sig_date, str):
                        sig_dt = datetime.fromisoformat(sig_date.replace("Z", "+00:00")).replace(tzinfo=None)
                    else:
                        sig_dt = sig_date
                    # For clinical trials, signal_date IS the completion date
                    if sig.get("signal_type") in ("clinical_trial", "fda_catalyst"):
                        days_until = (sig_dt - datetime.utcnow()).days
                    else:
                        estimated_catalyst = sig_dt + timedelta(days=120)
                        days_until = (estimated_catalyst - datetime.utcnow()).days
                except (ValueError, TypeError):
                    pass

        # Boost catalyst weight for clinical trial signals with real data
        cat_weight = CATALYST_WEIGHTS.get(cat_type, 0.3)
        if sig.get("signal_type") == "clinical_trial" and "phase" in raw:
            phase = str(raw.get("phase", "")).upper()
            if "PHASE3" in phase:
                cat_weight = max(cat_weight, 0.90)
            elif "PHASE2" in phase:
                cat_weight = max(cat_weight, 0.70)

        catalysts.append({
            "type": cat_type,
            "weight": cat_weight,
            "days_until": days_until,
            "source_signal": sig.get("signal_type"),
            "signal_id": sig.get("signal_id"),
            "notes": sig.get("notes"),
        })

    return catalysts


def detect_catalysts_from_filings(filing_text: str) -> List[Dict[str, Any]]:
    """
    NLP-lite catalyst detection from SEC filing text.
    Looks for forward-looking statements about catalysts.
    """
    text = filing_text.lower()
    catalysts = []

    patterns = {
        "fda_pdufa": ["pdufa", "prescription drug user fee", "target action date"],
        "fda_approval": ["fda approval", "new drug application", "biologics license"],
        "clinical_trial_data": ["phase 3", "phase iii", "pivotal trial", "primary endpoint",
                                "topline data", "clinical results"],
        "patent_grant": ["patent issu", "patent grant", "intellectual property"],
        "patent_litigation_ruling": ["patent litigation", "markman hearing", "claim construction"],
        "merger_acquisition": ["merger agreement", "definitive agreement", "acquisition of"],
        "contract_award": ["contract award", "indefinite delivery", "task order"],
        "regulatory_approval": ["regulatory approval", "marketing authorization", "eua"],
    }

    for cat_type, keywords in patterns.items():
        matches = [kw for kw in keywords if kw in text]
        if matches:
            catalysts.append({
                "type": cat_type,
                "weight": CATALYST_WEIGHTS.get(cat_type, 0.3),
                "matched_keywords": matches,
                "days_until": None,  # Can't determine from text alone
            })

    return catalysts


def score_binary_catalyst(
    market_cap: Optional[float],
    cash_runway_months: Optional[float],
    signals: List[Dict[str, Any]],
    filing_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute Lens 1 composite score for binary catalyst potential.

    Returns:
        catalyst_score (0.0-1.0)
        catalyst_type (best catalyst found)
        catalyst_proximity_days
        catalyst_details (full breakdown)
    """
    # Gather all catalysts
    catalysts = detect_catalysts_from_signals(signals)
    if filing_text:
        catalysts.extend(detect_catalysts_from_filings(filing_text))

    if not catalysts:
        return {
            "catalyst_score": 0.0,
            "catalyst_type": None,
            "catalyst_proximity_days": None,
            "catalyst_details": {"reason": "no_catalysts_detected"},
        }

    # Find the strongest catalyst
    best = max(catalysts, key=lambda c: c["weight"])
    best_type = best["type"]
    best_days = best.get("days_until")

    # Compute sub-scores
    mcap_s = _inverse_mcap_score(market_cap)
    prox_s = _catalyst_proximity_score(best_days)
    runway_s = _cash_runway_factor(cash_runway_months)
    catalyst_w = best["weight"]

    # Composite: catalyst_weight × proximity × inverse_mcap × runway
    # Weighted: 30% catalyst quality, 25% proximity, 25% mcap asymmetry, 20% runway
    composite = (
        0.30 * catalyst_w +
        0.25 * prox_s +
        0.25 * mcap_s +
        0.20 * runway_s
    )
    composite = round(min(max(composite, 0.0), 1.0), 4)

    cited_ids = [c["signal_id"] for c in catalysts if c.get("signal_id")]

    return {
        "catalyst_score": composite,
        "catalyst_type": best_type,
        "catalyst_proximity_days": best_days,
        "cited_signal_ids": cited_ids,
        "catalyst_details": {
            "components": {
                "catalyst_weight": catalyst_w,
                "proximity": prox_s,
                "inverse_mcap": mcap_s,
                "cash_runway": runway_s,
            },
            "all_catalysts": catalysts,
            "cited_signal_ids": cited_ids,
            "market_cap": market_cap,
            "cash_runway_months": cash_runway_months,
        },
    }
