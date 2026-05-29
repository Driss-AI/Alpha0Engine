"""
Trial-to-Entity Matcher
=========================
Maps ClinicalTrials.gov sponsors to tracked entities.
Uses normalized company name matching since CT.gov sponsor names
don't include tickers or CIKs.

Examples:
  "Supernus Pharmaceuticals, Inc." → entity with name "Supernus Pharmaceuticals"
  "Acacia Research Corporation" → entity with ticker "ACTG"
"""
import logging
import re
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Suffixes to strip for fuzzy matching
CORP_SUFFIXES = [
    r"\binc\.?\b", r"\bcorp\.?\b", r"\bcorporation\b", r"\bltd\.?\b",
    r"\bllc\b", r"\bplc\b", r"\bco\.?\b", r"\bcompany\b",
    r"\bpharmaceuticals?\b", r"\btherapeutics?\b", r"\bbiosciences?\b",
    r"\bbiopharma\b", r"\bbiotech\b", r"\boncology\b", r"\bmedical\b",
    r"\bhealth\b", r"\bsciences?\b", r"\bholdings?\b", r"\bgroup\b",
    r"\blimited\b", r"\bs\.?a\.?\b", r"\bse\b", r"\bn\.?v\.?\b",
    r",", r"\.", r"'",
]


def _normalize(name: str) -> str:
    """Normalize a company name for fuzzy matching."""
    n = name.lower().strip()
    for suffix in CORP_SUFFIXES:
        n = re.sub(suffix, "", n, flags=re.IGNORECASE)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _match_score(sponsor: str, entity_name: str) -> float:
    """
    Compute a similarity score between sponsor and entity name.
    Returns 0.0-1.0.
    """
    s_norm = _normalize(sponsor)
    e_norm = _normalize(entity_name)

    if not s_norm or not e_norm:
        return 0.0

    # Exact match after normalization
    if s_norm == e_norm:
        return 1.0

    # One contains the other
    if s_norm in e_norm or e_norm in s_norm:
        shorter = min(len(s_norm), len(e_norm))
        longer = max(len(s_norm), len(e_norm))
        return 0.7 + 0.3 * (shorter / longer)

    # Word overlap
    s_words = set(s_norm.split())
    e_words = set(e_norm.split())
    if not s_words or not e_words:
        return 0.0

    overlap = s_words & e_words
    if not overlap:
        return 0.0

    # Jaccard-ish: overlap / union, weighted toward the shorter name
    jaccard = len(overlap) / len(s_words | e_words)
    coverage = len(overlap) / min(len(s_words), len(e_words))

    return 0.5 * jaccard + 0.5 * coverage


def match_sponsor_to_entities(
    sponsor_name: str,
    entities: List[Dict[str, Any]],
    threshold: float = 0.6,
) -> Optional[Dict[str, Any]]:
    """
    Find the best matching entity for a trial sponsor.
    Returns the entity dict if match score >= threshold, else None.
    """
    if not sponsor_name or not entities:
        return None

    best_match = None
    best_score = 0.0

    for entity in entities:
        name = entity.get("name", "")
        score = _match_score(sponsor_name, name)

        if score > best_score:
            best_score = score
            best_match = entity

    if best_score >= threshold and best_match:
        best_match["match_score"] = best_score
        return best_match

    return None


def build_entity_index(entities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build a lookup index for fast sponsor matching.
    Groups entities by first word of normalized name.
    """
    index = {}
    for entity in entities:
        name = _normalize(entity.get("name", ""))
        if not name:
            continue
        first_word = name.split()[0] if name.split() else ""
        if first_word:
            if first_word not in index:
                index[first_word] = []
            index[first_word].append(entity)
    return index


def match_sponsor_indexed(
    sponsor_name: str,
    index: Dict[str, List[Dict[str, Any]]],
    all_entities: List[Dict[str, Any]],
    threshold: float = 0.6,
) -> Optional[Dict[str, Any]]:
    """
    Fast matching using the pre-built index.
    Checks indexed candidates first, falls back to full scan.
    """
    sponsor_norm = _normalize(sponsor_name)
    if not sponsor_norm:
        return None

    first_word = sponsor_norm.split()[0] if sponsor_norm.split() else ""

    # Check indexed candidates first (fast path)
    candidates = index.get(first_word, [])
    result = match_sponsor_to_entities(sponsor_name, candidates, threshold)
    if result:
        return result

    # Fall back to full scan (slower but catches edge cases)
    return match_sponsor_to_entities(sponsor_name, all_entities, threshold)
