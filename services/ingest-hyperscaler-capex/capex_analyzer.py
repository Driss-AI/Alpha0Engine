"""
Hyperscaler capex analysis (Sprint 8.4) — pure functions, unit-testable.

The fetch layer (yfinance) is separated into main.py so this module has no
network dependency and can be tested against fixtures.
"""
from __future__ import annotations

from typing import Any, Optional

# YoY capex growth above this fraction = inflection (leading AI-infra demand signal).
INFLECTION_THRESHOLD = 0.30


def fiscal_period_label(year: int, quarter: int) -> str:
    return f"{year}Q{quarter}"


def compute_yoy(current: Optional[float], year_ago: Optional[float]) -> Optional[float]:
    """YoY growth as a fraction (0.34 = +34%). None if inputs unusable."""
    if current is None or year_ago is None:
        return None
    if year_ago == 0:
        return None
    return round((current - year_ago) / abs(year_ago), 4)


def is_inflection(yoy_pct: Optional[float]) -> bool:
    return yoy_pct is not None and yoy_pct > INFLECTION_THRESHOLD


# Lane the hyperscaler-capex signal belongs to (AI-infrastructure supply chain).
CONTEXT_LANE_ID = "L1_AI_INFRA"
CONTEXT_TYPE = "hyperscaler_capex_inflection"


def derive_market_context(all_records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Reduce per-company capex records to a single market-wide context signal.

    Sprint 11.3: the capex worker used to write `hyperscaler_capex` rows that
    nothing read (dead-end table). This turns an inflection into a market-WIDE
    `hyperscaler_capex_inflection` context the demand-rider lens consumes, so a
    real macro signal lifts the whole L1 AI-infra lane.

    Picks the most recent fiscal period that has ≥1 inflecting hyperscaler and
    reports the strongest YoY in that period. Returns None when nothing is
    inflecting (so the caller writes/keeps no active context).
    """
    inflecting = [r for r in all_records if r.get("is_inflection") and r.get("capex_yoy_pct") is not None]
    if not inflecting:
        return None

    # Latest period present among inflecting records ("2026Q1" sorts correctly).
    latest_period = max(r["fiscal_period"] for r in inflecting)
    in_period = [r for r in inflecting if r["fiscal_period"] == latest_period]
    max_yoy = max(r["capex_yoy_pct"] for r in in_period)
    tickers = sorted({r["ticker"] for r in in_period})

    return {
        "context_type": CONTEXT_TYPE,
        "lane_id": CONTEXT_LANE_ID,
        "value": round(max_yoy, 4),
        "period": latest_period,
        "source": "hyperscaler-capex",
        "details": {
            "inflecting_tickers": tickers,
            "max_yoy_pct": round(max_yoy, 4),
            "count": len(in_period),
        },
    }


def build_capex_records(
    ticker: str,
    company: str,
    quarterly_capex: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn a time-ordered list of quarterly capex points into capex records.

    Args:
        quarterly_capex: list of {"year": int, "quarter": int, "capex_usd": float}
            Capex is stored as a positive magnitude (we abs() yfinance's negative).
            Need not be sorted; this function sorts by (year, quarter).

    Returns one record per quarter with YoY (vs same quarter prior year) + inflection flag.
    """
    pts = sorted(quarterly_capex, key=lambda p: (p["year"], p["quarter"]))
    by_yq = {(p["year"], p["quarter"]): abs(p["capex_usd"]) if p.get("capex_usd") is not None else None
             for p in pts}

    records = []
    for p in pts:
        y, q = p["year"], p["quarter"]
        capex = by_yq[(y, q)]
        year_ago = by_yq.get((y - 1, q))
        yoy = compute_yoy(capex, year_ago)
        records.append({
            "ticker": ticker,
            "company": company,
            "fiscal_period": fiscal_period_label(y, q),
            "capex_usd": capex,
            "capex_yoy_pct": yoy,
            "is_inflection": is_inflection(yoy),
        })
    return records
