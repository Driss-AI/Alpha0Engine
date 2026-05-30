"""
8-K Filing Parser
==================
Classifies 8-K filings by item type and detects catalyst keywords.
8-K items that matter for 1000x setups:
  - Item 1.01: Material Definitive Agreement (M&A, licensing)
  - Item 2.01: Completion of Acquisition/Disposition
  - Item 5.02: Director/Officer Departure/Appointment
  - Item 7.01: Reg FD Disclosure (FDA results, clinical data, guidance)
  - Item 8.01: Other Events (catch-all for material events)
"""
import logging
import re
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# ── Catalyst keyword patterns ────────────────────────────
CATALYST_PATTERNS = {
    "fda_approval": [
        r"fda\s+approv", r"pdufa", r"new drug application", r"nda\s+approv",
        r"biologics license", r"bla\s+approv", r"510\(k\)", r"eua\b",
        r"breakthrough\s+therapy", r"fast\s+track", r"priority\s+review",
    ],
    "clinical_trial_data": [
        r"phase\s*(3|iii|2|ii)\s*(trial|study|data|results)",
        r"topline\s*(data|results)", r"primary\s+endpoint",
        r"pivotal\s+(trial|study)", r"clinical\s+results",
        r"statistically\s+significant", r"overall\s+survival",
        r"progression.free\s+survival",
    ],
    "merger_acquisition": [
        r"definitive\s+agreement", r"merger\s+agreement",
        r"acquisition\s+of", r"to\s+acquire", r"tender\s+offer",
        r"buyout", r"going\s+private", r"change\s+of\s+control",
    ],
    "contract_award": [
        r"contract\s+award", r"indefinite\s+delivery",
        r"task\s+order", r"government\s+contract",
        r"department\s+of\s+defense", r"\bdod\b", r"darpa",
    ],
    "partnership": [
        r"strategic\s+(partnership|alliance|collaboration)",
        r"licensing\s+agreement", r"co-development",
        r"commercialization\s+agreement", r"royalt(y|ies)",
    ],
    "offering": [
        r"public\s+offering", r"private\s+placement",
        r"shelf\s+registration", r"at.the.market",
    ],
    # ── Sprint 8.3: AI Infrastructure (L1) categories ────────────────────────
    "hyperscaler_contract": [
        r"hyperscaler", r"(microsoft|amazon|aws|google|meta|oracle)\s+",
        r"cloud\s+services\s+agreement", r"gpu\s+hosting", r"colocation\s+agreement",
        r"capacity\s+agreement",
    ],
    "ppa_signed": [
        r"power\s+purchase\s+agreement", r"\bppa\b", r"behind.the.meter",
        r"power\s+supply\s+agreement", r"energy\s+services\s+agreement",
        r"\d+\s*(mw|megawatt|gw|gigawatt)",
    ],
    "data_center_lease": [
        r"data\s+center\s+lease", r"build.to.suit", r"colocation",
        r"critical\s+it\s+load", r"data\s+center\s+capacity",
    ],
    "gpu_order": [
        r"gpu\s+(order|purchase|procurement)", r"(h100|h200|gb200|blackwell)",
        r"accelerated\s+computing", r"nvidia\s+(gpu|chips|order)",
    ],
    # ── Sprint 8.3: bearish / risk categories ────────────────────────────────
    "going_concern": [
        r"going\s+concern", r"substantial\s+doubt", r"ability\s+to\s+continue",
    ],
    "reverse_split": [
        r"reverse\s+(stock\s+)?split", r"share\s+consolidation",
    ],
    "delisting": [
        r"delisting", r"notice\s+of\s+noncompliance", r"minimum\s+bid\s+price",
        r"nasdaq\s+notification",
    ],
}

# Map 8-K catalyst categories to lane + lane catalyst_type (Sprint 8.3).
# Categories not listed here are lane-agnostic.
CATEGORY_LANE_MAP = {
    "hyperscaler_contract": ("L1_AI_INFRA", "hyperscaler_contract", "data_center"),
    "ppa_signed":           ("L1_AI_INFRA", "ppa_signed", "power"),
    "data_center_lease":    ("L1_AI_INFRA", "data_center_lease", "data_center"),
    "gpu_order":            ("L1_AI_INFRA", "gpu_order", "gpu_cloud"),
    "contract_award":       ("L1_AI_INFRA", "gov_contract", "power"),
    "fda_approval":         ("L2_BIOTECH", "fda_approval", "fda_decision"),
    "clinical_trial_data":  ("L2_BIOTECH", "trial_readout", "clinical_trial"),
}

# 8-K categories that map to risk red flags (Sprint 8.3 → feeds S7.6 detect_red_flags).
CATEGORY_RED_FLAGS = {
    "offering": "recent_dilutive_offering",
    "going_concern": "going_concern",
    "reverse_split": "reverse_split",
    "delisting": "nasdaq_delisting_notice",
}

# 8-K item number → category
ITEM_CATEGORIES = {
    "1.01": "agreement",
    "1.02": "termination",
    "2.01": "acquisition",
    "2.02": "financial_results",
    "2.05": "cost_restructuring",
    "2.06": "impairment",
    "3.01": "delisting",
    "5.01": "governance",
    "5.02": "officer_change",
    "5.07": "shareholder_vote",
    "7.01": "reg_fd",
    "8.01": "other_event",
}


def extract_items(text: str) -> List[str]:
    """Extract 8-K item numbers from filing text."""
    items = re.findall(r"Item\s+(\d+\.\d+)", text, re.IGNORECASE)
    return list(set(items))


def classify_catalyst(text: str) -> Dict[str, Any]:
    """
    Classify the 8-K filing by catalyst type using keyword matching.
    Returns the strongest catalyst match with confidence.
    """
    text_lower = text.lower()
    results = {}

    for catalyst_type, patterns in CATALYST_PATTERNS.items():
        matches = []
        for pattern in patterns:
            found = re.findall(pattern, text_lower)
            if found:
                matches.extend(found)

        if matches:
            # Confidence based on number of pattern matches
            confidence = min(len(matches) / 3.0, 1.0)
            results[catalyst_type] = {
                "confidence": round(confidence, 3),
                "match_count": len(matches),
            }

    if not results:
        return {"catalyst_type": None, "confidence": 0.0, "all_matches": {}}

    best = max(results, key=lambda k: results[k]["confidence"])
    return {
        "catalyst_type": best,
        "confidence": results[best]["confidence"],
        "all_matches": results,
    }


def compute_signal_value(
    items: List[str],
    catalyst: Dict[str, Any],
) -> float:
    """
    Signal value based on 8-K item type and catalyst classification.
    FDA/clinical results = highest, offerings = lowest.
    """
    cat_type = catalyst.get("catalyst_type")
    confidence = catalyst.get("confidence", 0)

    # Base by catalyst type
    base_scores = {
        "fda_approval": 0.90,
        "clinical_trial_data": 0.80,
        "merger_acquisition": 0.75,
        # AI-infra contracts are high-signal demand confirmation
        "hyperscaler_contract": 0.85,
        "ppa_signed": 0.75,
        "data_center_lease": 0.70,
        "gpu_order": 0.80,
        "contract_award": 0.65,
        "partnership": 0.55,
        "offering": 0.25,        # Dilutive — bearish
        "going_concern": 0.10,   # Bearish red flag
        "reverse_split": 0.10,
        "delisting": 0.10,
    }
    base = base_scores.get(cat_type, 0.40)

    # Item-based adjustments
    if "7.01" in items:  # Reg FD — often material news
        base = max(base, 0.50)
    if "1.01" in items:  # Material agreement
        base = max(base, 0.55)
    if "2.01" in items:  # Acquisition complete
        base = max(base, 0.60)

    # Scale by confidence
    return round(base * (0.5 + 0.5 * confidence), 4)


def is_catalyst_filing(items: List[str], catalyst: Dict[str, Any]) -> bool:
    """Check if this 8-K contains a meaningful catalyst for the screener."""
    # Skip routine filings
    routine_only = all(
        item in ("2.02", "5.02", "5.07", "9.01")
        for item in items
    )
    if routine_only and not catalyst.get("catalyst_type"):
        return False

    # Must have either a catalyst keyword or a significant item number
    significant_items = {"1.01", "2.01", "7.01", "8.01"}
    has_significant_item = bool(set(items) & significant_items)

    return has_significant_item or catalyst.get("catalyst_type") is not None


def lane_for_catalyst(catalyst_type: str | None) -> Dict[str, Any]:
    """Map a classified catalyst category to (lane_id, lane_catalyst_type, bottleneck).

    Returns {} for lane-agnostic categories (Sprint 8.3).
    """
    if not catalyst_type:
        return {}
    mapped = CATEGORY_LANE_MAP.get(catalyst_type)
    if not mapped:
        return {}
    lane_id, lane_catalyst_type, bottleneck = mapped
    return {"lane_id": lane_id, "catalyst_type": lane_catalyst_type, "bottleneck": bottleneck}


def red_flags_from_classification(catalyst: Dict[str, Any]) -> List[str]:
    """Extract red flags from ALL matched categories in a classification (Sprint 8.3).

    These feed risk_engine.detect_red_flags(extra_flags=...) — e.g. an 8-K that
    matches both 'offering' and 'going_concern' returns both flags.
    """
    all_matches = catalyst.get("all_matches", {})
    flags = []
    for category in all_matches:
        flag = CATEGORY_RED_FLAGS.get(category)
        if flag:
            flags.append(flag)
    # Also include the headline category if it's a red-flag type.
    head = catalyst.get("catalyst_type")
    if head in CATEGORY_RED_FLAGS and CATEGORY_RED_FLAGS[head] not in flags:
        flags.append(CATEGORY_RED_FLAGS[head])
    return flags
