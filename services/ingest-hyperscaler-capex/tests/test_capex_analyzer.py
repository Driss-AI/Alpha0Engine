"""Unit tests for capex analysis (Sprint 8.4)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from capex_analyzer import (
    compute_yoy, is_inflection, build_capex_records, fiscal_period_label,
    derive_market_context,
)


def test_compute_yoy():
    assert compute_yoy(134, 100) == 0.34
    assert compute_yoy(100, 100) == 0.0
    assert compute_yoy(50, 100) == -0.5
    assert compute_yoy(100, None) is None
    assert compute_yoy(None, 100) is None
    assert compute_yoy(100, 0) is None


def test_is_inflection():
    assert is_inflection(0.34) is True
    assert is_inflection(0.30) is False    # strictly greater than threshold
    assert is_inflection(0.31) is True
    assert is_inflection(0.10) is False
    assert is_inflection(None) is False


def test_fiscal_period_label():
    assert fiscal_period_label(2026, 1) == "2026Q1"


def test_build_records_computes_yoy_against_same_quarter():
    points = [
        {"year": 2025, "quarter": 1, "capex_usd": -10e9},  # yfinance gives negative
        {"year": 2026, "quarter": 1, "capex_usd": -14e9},  # +40% YoY -> inflection
        {"year": 2025, "quarter": 2, "capex_usd": -10e9},
        {"year": 2026, "quarter": 2, "capex_usd": -11e9},  # +10% -> no inflection
    ]
    recs = build_capex_records("MSFT", "Microsoft", points)
    by_period = {r["fiscal_period"]: r for r in recs}

    # capex stored as positive magnitude
    assert by_period["2026Q1"]["capex_usd"] == 14e9
    assert by_period["2026Q1"]["capex_yoy_pct"] == 0.4
    assert by_period["2026Q1"]["is_inflection"] is True

    assert by_period["2026Q2"]["capex_yoy_pct"] == 0.1
    assert by_period["2026Q2"]["is_inflection"] is False

    # first year has no prior-year comparison
    assert by_period["2025Q1"]["capex_yoy_pct"] is None
    assert by_period["2025Q1"]["is_inflection"] is False


def test_build_records_sorts_unordered_input():
    points = [
        {"year": 2026, "quarter": 1, "capex_usd": -14e9},
        {"year": 2025, "quarter": 1, "capex_usd": -10e9},
    ]
    recs = build_capex_records("AMZN", "Amazon", points)
    assert recs[0]["fiscal_period"] == "2025Q1"
    assert recs[1]["fiscal_period"] == "2026Q1"


# ── S11.3: market-wide context derivation ──────────────────────────

def test_derive_market_context_none_when_no_inflection():
    recs = [
        {"ticker": "MSFT", "fiscal_period": "2026Q1", "capex_yoy_pct": 0.10, "is_inflection": False},
        {"ticker": "AMZN", "fiscal_period": "2026Q1", "capex_yoy_pct": None, "is_inflection": False},
    ]
    assert derive_market_context(recs) is None
    assert derive_market_context([]) is None


def test_derive_market_context_single_inflection():
    recs = [
        {"ticker": "MSFT", "fiscal_period": "2026Q1", "capex_yoy_pct": 0.42, "is_inflection": True},
        {"ticker": "META", "fiscal_period": "2026Q1", "capex_yoy_pct": 0.10, "is_inflection": False},
    ]
    ctx = derive_market_context(recs)
    assert ctx is not None
    assert ctx["context_type"] == "hyperscaler_capex_inflection"
    assert ctx["lane_id"] == "L1_AI_INFRA"
    assert ctx["period"] == "2026Q1"
    assert ctx["value"] == 0.42
    assert ctx["details"]["inflecting_tickers"] == ["MSFT"]


def test_derive_market_context_picks_latest_period_and_max_yoy():
    recs = [
        # older inflection — should be ignored in favor of the latest period
        {"ticker": "MSFT", "fiscal_period": "2025Q4", "capex_yoy_pct": 0.90, "is_inflection": True},
        # latest period: two inflecting hyperscalers, report the stronger one
        {"ticker": "AMZN", "fiscal_period": "2026Q1", "capex_yoy_pct": 0.35, "is_inflection": True},
        {"ticker": "GOOGL", "fiscal_period": "2026Q1", "capex_yoy_pct": 0.55, "is_inflection": True},
    ]
    ctx = derive_market_context(recs)
    assert ctx["period"] == "2026Q1"
    assert ctx["value"] == 0.55
    assert ctx["details"]["inflecting_tickers"] == ["AMZN", "GOOGL"]
    assert ctx["details"]["count"] == 2
