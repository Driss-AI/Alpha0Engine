"""
Brain Analyst — Module 3
=========================
Calls Claude API with a structured evidence bundle and returns
a JSON opportunity assessment. The LLM is constrained to ONLY
reference data from the evidence bundle — no training knowledge.

Every claim must cite a source_id from the evidence.
"""
import os
import json
import logging
from typing import Dict, Any, Optional

import anthropic

logger = logging.getLogger("brain.analyst")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are the Alpha0 Brain — an autonomous investment analyst that identifies \
asymmetric-return opportunities (10x–1000x potential) in public equities.

## ABSOLUTE RULES
1. You may ONLY reference data provided in the evidence bundle below. \
NEVER use your training knowledge about companies, prices, or events.
2. Every factual claim MUST cite a source_id from the evidence (e.g. signal:abc123, \
screen:def456). Uncited claims will be stripped.
3. If the evidence is insufficient to form a thesis, return conviction "NONE".
4. Be brutally honest. Most companies are NOT 10x opportunities. Say so.
5. You are sector-agnostic. Judge purely on evidence strength.

## OUTPUT FORMAT
Return a single JSON object (no markdown, no commentary) with this exact schema:

{
  "verdict": "OPPORTUNITY" | "PASS" | "INSUFFICIENT_DATA",
  "conviction": "HIGH" | "MEDIUM" | "LOW" | "NONE",
  "confidence_score": <float 0.0-1.0>,
  "thesis": "<one paragraph investment thesis>",
  "thesis_type": "catalyst" | "earnings" | "demand" | "float" | "convergence" | "multi",
  "narrative": "<detailed multi-paragraph analysis with [source_id] citations>",
  "upside_scenario": "<bull case with cited evidence>",
  "downside_scenario": "<bear case with cited evidence>",
  "return_multiple": <float, e.g. 10.0 for 10x potential, null if can't estimate>,
  "time_horizon": "short" | "medium" | "long",
  "key_catalysts": [
    {"description": "<catalyst>", "source_id": "<id>", "expected_date": "<ISO or null>", "impact": "high"|"medium"|"low"}
  ],
  "key_signals": [
    {"source_id": "<id>", "summary": "<one-line summary of what this signal shows>"}
  ],
  "risk_factors": [
    {"description": "<risk>", "source_id": "<id or null>", "severity": "high"|"medium"|"low"}
  ],
  "evidence_quality": {
    "signal_count": <int>,
    "source_diversity": <int>,
    "lenses_active": <int>,
    "data_freshness": "fresh" | "stale" | "mixed",
    "gaps": ["<missing data that would strengthen/weaken thesis>"]
  }
}

If verdict is "PASS" or "INSUFFICIENT_DATA", still fill in thesis (explain why) and \
key fields. conviction must be "NONE" for INSUFFICIENT_DATA.
"""


def _build_user_prompt(candidate: Dict[str, Any], evidence: Dict[str, Any]) -> str:
    """Build the user message with candidate context and full evidence bundle."""
    entity = evidence.get("entity", {})
    stats = evidence.get("stats", {})

    header = (
        f"## Candidate: {entity.get('name', 'Unknown')} ({entity.get('ticker', '?')})\n"
        f"Sector: {entity.get('sector', 'Unknown')} | "
        f"Type: {entity.get('entity_type', 'Unknown')}\n"
        f"Selection reasons: {'; '.join(candidate.get('reasons', []))}\n"
        f"Priority score: {candidate.get('priority', 0):.3f} | "
        f"Selection paths: {candidate.get('path_count', 1)}\n\n"
        f"## Evidence Summary\n"
        f"Total evidence pieces: {stats.get('total_evidence_pieces', 0)} | "
        f"Sources: {stats.get('source_diversity', 0)} | "
        f"Signals: {stats.get('signal_count', 0)}\n\n"
    )

    evidence_json = json.dumps(evidence, indent=2, default=str)

    return (
        f"{header}"
        f"## Full Evidence Bundle\n"
        f"```json\n{evidence_json}\n```\n\n"
        f"Analyze this company. Is this a genuine asymmetric opportunity? "
        f"Cite source_ids for every claim."
    )


async def analyze_candidate(
    candidate: Dict[str, Any],
    evidence: Dict[str, Any],
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Send evidence bundle to Claude and get structured opportunity analysis.

    Returns parsed JSON dict or None on failure.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.error("ANTHROPIC_API_KEY not set")
        return None

    client = anthropic.AsyncAnthropic(api_key=key)
    user_msg = _build_user_prompt(candidate, evidence)

    entity_name = evidence.get("entity", {}).get("name", "Unknown")
    ticker = evidence.get("entity", {}).get("ticker", "?")
    logger.info(f"Analyzing {entity_name} ({ticker})...")

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw_text = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

        analysis = json.loads(raw_text)

        logger.info(
            f"  {entity_name}: verdict={analysis.get('verdict')}, "
            f"conviction={analysis.get('conviction')}, "
            f"confidence={analysis.get('confidence_score', 0):.2f}"
        )

        analysis["_usage"] = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"  {entity_name}: Failed to parse LLM JSON: {e}")
        logger.debug(f"  Raw response: {raw_text[:500]}")
        return None
    except anthropic.APIError as e:
        logger.error(f"  {entity_name}: Claude API error: {e}")
        return None
    except Exception as e:
        logger.error(f"  {entity_name}: Unexpected error in analysis: {e}")
        return None
