"""
Analyst — scoped LLM deep-dives that connect dots the lenses can't.
===================================================================
The mechanical lenses find the shortlist cheaply; this layer reasons about
the FEW names that matter: new DEEP_DIVE+ alerts and followed stocks whose
state changed. It writes the bull case, the bear case, non-obvious
connections, and what to verify — grounded ONLY in the dossier we hand it.

Cost containment (lesson from the deleted `brain` service, which burned an
API call per candidate per night):
  - runs only where a human will actually read the output
  - hard per-run call cap (ANALYST_MAX_CALLS_PER_RUN, default 8)
  - degrades gracefully: no ANTHROPIC_API_KEY → no takes, everything else works
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("alert-engine.analyst")

ANALYST_MODEL = "claude-opus-4-8"
MAX_CALLS_PER_RUN = int(os.environ.get("ANALYST_MAX_CALLS_PER_RUN", "8"))

_calls_this_run = 0

TAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "bull_case": {"type": "string"},
        "bear_case": {"type": "string"},
        "dot_connections": {
            "type": "array", "items": {"type": "string"},
        },
        "what_would_i_verify": {
            "type": "array", "items": {"type": "string"},
        },
        "conviction": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    },
    "required": ["bull_case", "bear_case", "dot_connections",
                 "what_would_i_verify", "conviction"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are the in-house analyst for a catalyst-driven micro-cap screening engine.
The engine's mechanical lenses already scored this candidate; your job is the
part they can't do: reason about the setup like a skeptical, creative analyst.

Rules:
- Ground every claim in the dossier provided. If the dossier doesn't support
  a claim, don't make it. Never invent prices, dates, or filings.
- Connect dots: second-order effects, who else benefits or is exposed, what
  the crowd is likely missing, how this setup rhymes with known archetypes.
- The bear case must be a genuine attempt to kill the thesis, not a token
  disclaimer. Dilution risk, catalyst slippage, and crowded-trade dynamics
  deserve particular suspicion in micro-caps.
- "what_would_i_verify" items must be concrete actions a human can take
  (a filing to read, a number to check, a date to confirm).
- This is research support, not investment advice; the human decides.
- Be terse. Two or three sentences per case; one line per dot connection."""


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def reset_run_budget() -> None:
    global _calls_this_run
    _calls_this_run = 0


def build_dossier(
    *,
    ticker: str,
    company: Optional[str],
    lane_name: Optional[str],
    bucket: Optional[str],
    thesis: Optional[dict],
    axes: Optional[dict],
    red_flags: Optional[list],
    mechanics: Optional[dict],
    catalysts: Optional[list] = None,
    recent_signals: Optional[list] = None,
    changes: Optional[list] = None,
) -> dict[str, Any]:
    """Everything the analyst may reason from — and nothing else."""
    return {
        "ticker": ticker,
        "company": company,
        "lane": lane_name,
        "bucket": bucket,
        "thesis": thesis or {},
        "axes": axes or {},
        "red_flags": red_flags or [],
        "mechanics": mechanics or {},
        "upcoming_catalysts": catalysts or [],
        "recent_signals": recent_signals or [],
        "changes_since_last_checkup": changes or [],
    }


def analyst_take(dossier: dict[str, Any]) -> Optional[dict[str, Any]]:
    """One structured take for one dossier. None when unconfigured, over
    budget, or on any API failure — callers must treat the take as optional."""
    global _calls_this_run

    if not is_configured():
        return None
    if _calls_this_run >= MAX_CALLS_PER_RUN:
        logger.info("analyst call budget exhausted for this run")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — analyst takes disabled")
        return None

    _calls_this_run += 1
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=ANALYST_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": TAKE_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "Dossier (the only facts you may use):\n"
                    + json.dumps(dossier, indent=2, sort_keys=True, default=str)
                ),
            }],
        )
        if response.stop_reason == "refusal":
            logger.warning(f"analyst request refused for {dossier.get('ticker')}")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text)
    except Exception as e:
        logger.error(f"analyst take failed for {dossier.get('ticker')}: {e}")
        return None


def format_take_lines(take: dict[str, Any]) -> list[str]:
    """Render a take as Telegram-ready lines."""
    lines = [f"🧠 Analyst take ({take.get('conviction', '?')} conviction)"]
    if take.get("bull_case"):
        lines.append(f"  Bull: {take['bull_case']}")
    if take.get("bear_case"):
        lines.append(f"  Bear: {take['bear_case']}")
    for dot in (take.get("dot_connections") or [])[:4]:
        lines.append(f"  🔗 {dot}")
    verify = take.get("what_would_i_verify") or []
    if verify:
        lines.append("  Verify: " + "; ".join(verify[:3]))
    return lines
