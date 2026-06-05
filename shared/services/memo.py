"""
Alert memo generator (Sprint 13.1) — deterministic, testable.

Turns an alert (or a live screener candidate) into a one-page, self-contained
research memo: everything a human needs to decide whether to dig in, plus the two
fields the alert template never had — **what would invalidate this** and **what to
check manually**. Built from the existing thesis + axes + red flags + mechanics,
so every line traces to data we already hold (no LLM).

`build_memo(...)` returns the structured memo; `render_memo_markdown(...)` renders
the one-pager. Missing inputs become explicit "n/a"/"none" rather than blanks.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.scoring.buckets import bucket_label


def _fmt_pct(x: Optional[float]) -> str:
    return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"


def _fmt_score(x: Optional[float]) -> str:
    return f"{x:.0f}" if isinstance(x, (int, float)) else "—"


def _price_setup(mechanics: dict[str, Any]) -> str:
    vol = mechanics.get("volume_ratio")
    bits = []
    if isinstance(vol, (int, float)):
        bits.append(f"volume {vol:.1f}x 30-day average")
    if mechanics.get("price_breakout"):
        bits.append("price breakout confirmed")
    return "; ".join(bits) if bits else "n/a"


def _float_setup(mechanics: dict[str, Any]) -> str:
    float_v = mechanics.get("float_label")
    if float_v is None:
        fv = mechanics.get("float")
        float_v = f"{fv:,.0f} sh" if isinstance(fv, (int, float)) else "n/a"
    short_v = mechanics.get("short_pct_float")
    return f"float {float_v}, short interest {_fmt_pct(short_v)}"


def _invalidation_conditions(
    thesis: dict[str, Any], red_flags: list[str]
) -> list[str]:
    """What, concretely, would break this thesis. Always returns ≥1 item."""
    out: list[str] = []
    ct = thesis.get("catalyst_type")
    cd = thesis.get("catalyst_date")
    if ct and cd:
        out.append(
            f"The {ct} dated {cd} slips, is withdrawn, or resolves negative "
            f"(e.g. miss / CRL / negative readout)."
        )
    if red_flags:
        out.append(f"Any open red flag is confirmed: {', '.join(red_flags)}.")
    bn = thesis.get("bottleneck")
    if bn and bn != "—":
        out.append(
            f"The {bn} bottleneck eases (new supply or a substitute), breaking "
            f"the scarcity thesis."
        )
    # Always-present backstop so the memo can never lack an invalidation line.
    out.append("Composite score re-rates below the alert level on the next screen.")
    return out


def _manual_checks(thesis: dict[str, Any], mechanics: dict[str, Any]) -> list[str]:
    """The minimum manual diligence before acting. Always returns ≥1 item."""
    out = [
        "Confirm float and short interest on a second source (exchange / data vendor).",
        "Read the latest 8-K / 10-Q for dilution (ATM, shelf) or going-concern language.",
        "Check liquidity: average daily $ volume vs your intended position size.",
    ]
    if thesis.get("catalyst_type") and thesis.get("catalyst_date"):
        out.append(
            "Verify the catalyst date against the primary source "
            "(company IR / regulator calendar)."
        )
    lane_id = thesis.get("lane_id")
    if lane_id == "L1_AI_INFRA":
        out.append(
            "Confirm the offtake/PPA/contract counterparty, capacity, and start date."
        )
    elif lane_id == "L2_BIOTECH":
        out.append(
            "Confirm the trial phase, primary endpoint, and enrollment on ClinicalTrials.gov."
        )
    return out


def build_memo(
    *,
    ticker: str,
    company: Optional[str],
    lane_name: str,
    bucket: str,
    thesis: dict[str, Any],
    axes: dict[str, Any],
    red_flags: Optional[list[str]] = None,
    mechanics: Optional[dict[str, Any]] = None,
    outcome: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the structured one-page memo.

    thesis:  Thesis.to_dict() — megatrend/bottleneck/exposure/why_now/evidence/
             catalyst_type/catalyst_date/lane_id
    axes:    {opportunity, risk, timing, confidence, tradability}
    outcome: optional realized returns for a matured alert (forward_return_*).
    """
    red_flags = red_flags or []
    mechanics = mechanics or {}
    evidence = thesis.get("evidence") or []

    ct = thesis.get("catalyst_type")
    cd = thesis.get("catalyst_date")

    return {
        "ticker": ticker,
        "company": company or ticker,
        "lane": lane_name or "—",
        "bucket": bucket_label(bucket),
        "why_now": thesis.get("why_now") or "n/a",
        "megatrend": thesis.get("megatrend") or "—",
        "bottleneck": thesis.get("bottleneck") or "—",
        "exposure": thesis.get("exposure") or "—",
        "catalyst": {"type": ct, "date": cd} if (ct and cd) else None,
        "evidence": [
            {"summary": e.get("summary") or e.get("source") or "evidence",
             "source_url": e.get("source_url")}
            for e in evidence
        ],
        "red_flags": red_flags,
        "axis_scores": {
            "opportunity": axes.get("opportunity"),
            "risk": axes.get("risk"),
            "timing": axes.get("timing"),
            "confidence": axes.get("confidence"),
            "tradability": axes.get("tradability"),
        },
        "price_setup": _price_setup(mechanics),
        "float_setup": _float_setup(mechanics),
        "what_would_invalidate": _invalidation_conditions(thesis, red_flags),
        "what_to_check_manually": _manual_checks(thesis, mechanics),
        "outcome": outcome,
    }


def render_memo_markdown(memo: dict[str, Any]) -> str:
    """Render the structured memo as a one-page markdown artifact."""
    ax = memo.get("axis_scores") or {}
    lines: list[str] = []
    lines.append(f"# {memo['ticker']} — {memo['company']}")
    lines.append(f"**Lane:** {memo['lane']}  ·  **Action:** {memo['bucket']} — do not buy blind")
    lines.append("")
    lines.append(f"**Why now:** {memo['why_now']}")
    lines.append("")
    lines.append(f"- **Megatrend:** {memo['megatrend']}")
    lines.append(f"- **Bottleneck:** {memo['bottleneck']}")
    lines.append(f"- **Exposure:** {memo['exposure']}")
    cat = memo.get("catalyst")
    lines.append(f"- **Catalyst:** {cat['type']} on {cat['date']}" if cat else "- **Catalyst:** none dated")
    lines.append("")

    lines.append("## Evidence")
    if memo["evidence"]:
        for e in memo["evidence"][:8]:
            url = e.get("source_url") or "(no url)"
            lines.append(f"- {e['summary']} ({url})")
    else:
        lines.append("- (no cited evidence — do not act)")
    lines.append("")

    lines.append("## Scores")
    lines.append(
        f"Opp {_fmt_score(ax.get('opportunity'))} | Risk {_fmt_score(ax.get('risk'))} | "
        f"Timing {_fmt_score(ax.get('timing'))} | Conf {_fmt_score(ax.get('confidence'))} | "
        f"Trade {_fmt_score(ax.get('tradability'))}"
    )
    lines.append(f"- **Price setup:** {memo['price_setup']}")
    lines.append(f"- **Float setup:** {memo['float_setup']}")
    rf = memo.get("red_flags") or []
    lines.append(f"- **Red flags:** {', '.join(rf) if rf else 'none critical'}")
    lines.append("")

    lines.append("## What would invalidate this")
    for c in memo["what_would_invalidate"]:
        lines.append(f"- {c}")
    lines.append("")

    lines.append("## What to check manually")
    for c in memo["what_to_check_manually"]:
        lines.append(f"- {c}")

    outcome = memo.get("outcome")
    if outcome:
        lines.append("")
        lines.append("## Outcome (realized)")
        lines.append(
            f"7d {_fmt_pct(outcome.get('forward_return_7d'))} | "
            f"30d {_fmt_pct(outcome.get('forward_return_30d'))} | "
            f"90d {_fmt_pct(outcome.get('forward_return_90d'))} | "
            f"max DD {_fmt_pct(outcome.get('max_drawdown'))}"
        )

    return "\n".join(lines)


def memo_summary_lines(memo: dict[str, Any]) -> list[str]:
    """Two-line summary for embedding in a short Telegram message (S13.3)."""
    invalidate = memo["what_would_invalidate"][0] if memo["what_would_invalidate"] else "n/a"
    check = memo["what_to_check_manually"][0] if memo["what_to_check_manually"] else "n/a"
    return [
        f"Would invalidate: {invalidate}",
        f"Check first: {check}",
    ]
