"""
Verification Layer — Brain Module 4
=====================================
Ensures every LLM claim is backed by real evidence.
Walks the analysis JSON and checks that every cited source_id
actually exists in the evidence bundle. Strips unverified claims.

Also enforces the threshold gate:
  - min 3 cited signals
  - min 2 active lenses
  - min 2 distinct data sources
"""
import re
import logging
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger("brain.verify")

# ── Threshold Gate ──────────────────────────────────────────
MIN_CITED_SIGNALS = 3
MIN_LENSES_ACTIVE = 2
MIN_SOURCE_DIVERSITY = 2


def _extract_all_source_ids(evidence: Dict[str, Any]) -> Set[str]:
    """Walk the evidence bundle and collect every source_id."""
    valid_ids: Set[str] = set()

    for signal in evidence.get("signals", []):
        if sid := signal.get("source_id"):
            valid_ids.add(sid)

    if screener := evidence.get("screener"):
        if sid := screener.get("source_id"):
            valid_ids.add(sid)

    if fundamentals := evidence.get("fundamentals"):
        if sid := fundamentals.get("source_id"):
            valid_ids.add(sid)

    if risk := evidence.get("risk"):
        if sid := risk.get("source_id"):
            valid_ids.add(sid)

    for catalyst in evidence.get("catalysts", []):
        if sid := catalyst.get("source_id"):
            valid_ids.add(sid)

    for event in evidence.get("timeline", []):
        if sid := event.get("source_id"):
            valid_ids.add(sid)

    for article in evidence.get("news", []):
        if sid := article.get("source_id"):
            valid_ids.add(sid)

    return valid_ids


# Pattern to match [source_id] citations in narrative text
_CITATION_PATTERN = re.compile(r"\[([a-z_]+:[a-f0-9\-]+)\]")


def _extract_cited_ids_from_text(text: str) -> Set[str]:
    """Pull all [source_id] citations from a narrative string."""
    return set(_CITATION_PATTERN.findall(text))


def _verify_list_items(
    items: List[Dict[str, Any]],
    valid_ids: Set[str],
    label: str,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Verify a list of dicts that each have a source_id field.
    Returns (verified_items, kept_count, stripped_count).
    """
    verified = []
    stripped = 0
    for item in items:
        sid = item.get("source_id")
        if sid and sid in valid_ids:
            verified.append(item)
        elif sid is None:
            verified.append(item)
        else:
            stripped += 1
            logger.debug(f"  Stripped {label} with invalid source_id: {sid}")
    return verified, len(verified), stripped


def verify_analysis(
    analysis: Dict[str, Any],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Verify an LLM analysis against its evidence bundle.

    1. Collect all valid source_ids from the evidence.
    2. Check every citation in the analysis.
    3. Strip items with invalid citations.
    4. Compute verification stats.

    Returns the analysis dict with a _verification block added.
    """
    valid_ids = _extract_all_source_ids(evidence)
    logger.info(f"Verification: {len(valid_ids)} valid source_ids in evidence")

    total_cited: Set[str] = set()
    total_invalid: Set[str] = set()

    # ── Verify narrative text citations ────────────────────────
    narrative = analysis.get("narrative", "")
    narrative_cited = _extract_cited_ids_from_text(narrative)
    narrative_valid = narrative_cited & valid_ids
    narrative_invalid = narrative_cited - valid_ids
    total_cited |= narrative_valid
    total_invalid |= narrative_invalid

    if narrative_invalid:
        logger.warning(f"  Narrative has {len(narrative_invalid)} invalid citations: {narrative_invalid}")
        for bad_id in narrative_invalid:
            narrative = narrative.replace(f"[{bad_id}]", "[citation removed]")
        analysis["narrative"] = narrative

    # ── Verify upside/downside scenarios ──────────────────────
    for field in ("upside_scenario", "downside_scenario", "thesis"):
        text = analysis.get(field, "") or ""
        cited = _extract_cited_ids_from_text(text)
        valid = cited & valid_ids
        invalid = cited - valid_ids
        total_cited |= valid
        total_invalid |= invalid
        if invalid:
            for bad_id in invalid:
                text = text.replace(f"[{bad_id}]", "[citation removed]")
            analysis[field] = text

    # ── Verify key_signals list ───────────────────────────────
    key_signals = analysis.get("key_signals", [])
    verified_signals, kept, stripped = _verify_list_items(key_signals, valid_ids, "key_signal")
    analysis["key_signals"] = verified_signals
    for s in verified_signals:
        if s.get("source_id"):
            total_cited.add(s["source_id"])

    # ── Verify key_catalysts list ─────────────────────────────
    key_catalysts = analysis.get("key_catalysts", [])
    verified_catalysts, _, cat_stripped = _verify_list_items(key_catalysts, valid_ids, "key_catalyst")
    analysis["key_catalysts"] = verified_catalysts
    for c in verified_catalysts:
        if c.get("source_id"):
            total_cited.add(c["source_id"])

    # ── Verify risk_factors list ──────────────────────────────
    risk_factors = analysis.get("risk_factors", [])
    verified_risks, _, risk_stripped = _verify_list_items(risk_factors, valid_ids, "risk_factor")
    analysis["risk_factors"] = verified_risks
    for r in verified_risks:
        if r.get("source_id"):
            total_cited.add(r["source_id"])

    # ── Compute citation coverage ─────────────────────────────
    source_types_cited = set()
    for sid in total_cited:
        prefix = sid.split(":")[0] if ":" in sid else "unknown"
        source_types_cited.add(prefix)

    verification = {
        "total_valid_source_ids": len(valid_ids),
        "total_cited": len(total_cited),
        "total_invalid_removed": len(total_invalid),
        "citation_coverage": len(total_cited) / len(valid_ids) if valid_ids else 0,
        "source_types_cited": sorted(source_types_cited),
        "signals_stripped": stripped,
        "catalysts_stripped": cat_stripped,
        "risks_stripped": risk_stripped,
        "cited_ids": sorted(total_cited),
        "invalid_ids": sorted(total_invalid),
    }

    analysis["_verification"] = verification

    logger.info(
        f"  Verified: {len(total_cited)} valid citations, "
        f"{len(total_invalid)} invalid removed, "
        f"coverage={verification['citation_coverage']:.1%}"
    )

    return analysis


def passes_threshold(
    analysis: Dict[str, Any],
    evidence: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Apply the publication threshold gate.

    Requirements to publish:
      1. verdict == "OPPORTUNITY"
      2. conviction != "NONE"
      3. >= MIN_CITED_SIGNALS verified citations
      4. >= MIN_LENSES_ACTIVE lenses firing
      5. >= MIN_SOURCE_DIVERSITY distinct data sources

    Returns (passes: bool, reasons: list of why it failed).
    """
    reasons: List[str] = []

    verdict = analysis.get("verdict", "PASS")
    if verdict != "OPPORTUNITY":
        reasons.append(f"verdict={verdict} (need OPPORTUNITY)")

    conviction = analysis.get("conviction", "NONE")
    if conviction == "NONE":
        reasons.append("conviction=NONE")

    verification = analysis.get("_verification", {})
    cited_count = verification.get("total_cited", 0)
    if cited_count < MIN_CITED_SIGNALS:
        reasons.append(f"cited_signals={cited_count} (need >={MIN_CITED_SIGNALS})")

    lenses = analysis.get("evidence_quality", {}).get("lenses_active", 0)
    screener = evidence.get("screener")
    if screener:
        lenses = max(lenses, screener.get("active_lenses", 0))
    if lenses < MIN_LENSES_ACTIVE:
        reasons.append(f"lenses_active={lenses} (need >={MIN_LENSES_ACTIVE})")

    source_diversity = len(verification.get("source_types_cited", []))
    if source_diversity < MIN_SOURCE_DIVERSITY:
        reasons.append(f"source_diversity={source_diversity} (need >={MIN_SOURCE_DIVERSITY})")

    passes = len(reasons) == 0

    if passes:
        logger.info(f"  THRESHOLD PASSED: {cited_count} citations, {lenses} lenses, {source_diversity} sources")
    else:
        logger.info(f"  Threshold failed: {'; '.join(reasons)}")

    return passes, reasons
