"""
Alert formatter (Sprint 9.6) — pure, testable.

Renders the MANDATORY alert template. Every alert must carry: megatrend,
bottleneck, exposure, evidence (with URLs), catalyst, mechanics, the 5-axis
scores, red flags, why-now, and the action line. Missing fields are made
explicit ("none"/"n/a") rather than silently dropped.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.scoring.buckets import bucket_label


def _fmt_pct(x: Optional[float]) -> str:
    return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"


def _fmt_score(x: Optional[float]) -> str:
    return f"{x:.0f}" if isinstance(x, (int, float)) else "—"


def build_dedupe_key(ticker: str, lane_id: Optional[str], bucket: str) -> str:
    return f"{ticker}:{lane_id or 'nolane'}:{bucket}"


def format_alert(
    *,
    ticker: str,
    company: Optional[str],
    lane_name: str,
    thesis: dict[str, Any],
    axes: dict[str, float],
    bucket: str,
    red_flags: list[str],
    mechanics: Optional[dict[str, Any]] = None,
) -> str:
    """Render the mandatory Telegram alert template as plain text.

    thesis: dict from Thesis.to_dict() (megatrend, bottleneck, exposure, evidence,
            why_now, catalyst_type, catalyst_date)
    axes:   {opportunity, risk, timing, confidence, tradability}
    """
    mechanics = mechanics or {}
    lines: list[str] = []
    lines.append(f"ALERT: {ticker} ({company or '—'})")
    lines.append(f"Lane: {lane_name}")
    lines.append(f"Megatrend: {thesis.get('megatrend', '—')}")
    lines.append(f"Bottleneck: {thesis.get('bottleneck', '—')}")
    lines.append(f"Exposure: {thesis.get('exposure', '—')}")
    lines.append("")

    # Evidence (each with URL)
    lines.append("Evidence:")
    evidence = thesis.get("evidence") or []
    if evidence:
        for ev in evidence[:5]:
            summary = ev.get("summary") or ev.get("source") or "evidence"
            url = ev.get("source_url") or "(no url)"
            lines.append(f"  • {summary} ({url})")
    else:
        lines.append("  • (no cited evidence — do not act)")
    lines.append("")

    # Catalyst
    ct = thesis.get("catalyst_type")
    cd = thesis.get("catalyst_date")
    if ct and cd:
        lines.append(f"Catalyst: {ct} on {cd}")
    else:
        lines.append("Catalyst: none dated")

    # Mechanics
    float_v = mechanics.get("float")
    short_v = mechanics.get("short_pct_float")
    vol_v = mechanics.get("volume_ratio")
    lines.append(
        f"Mechanics: float {mechanics.get('float_label', float_v if float_v is not None else 'n/a')}, "
        f"short interest {_fmt_pct(short_v)}, "
        f"volume {f'{vol_v:.1f}x avg' if isinstance(vol_v, (int, float)) else 'n/a'}"
    )
    lines.append("")

    # Scores
    lines.append(
        f"Scores: Opp {_fmt_score(axes.get('opportunity'))} | "
        f"Risk {_fmt_score(axes.get('risk'))} | "
        f"Timing {_fmt_score(axes.get('timing'))} | "
        f"Conf {_fmt_score(axes.get('confidence'))} | "
        f"Trade {_fmt_score(axes.get('tradability'))}"
    )
    lines.append(f"Red flags: {', '.join(red_flags) if red_flags else 'none critical'}")
    lines.append(f"Why now: {thesis.get('why_now', '—')}")
    lines.append("")
    lines.append(f"Action: {bucket_label(bucket)} — do not buy blind")

    return "\n".join(lines)
