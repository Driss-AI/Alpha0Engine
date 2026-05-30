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
