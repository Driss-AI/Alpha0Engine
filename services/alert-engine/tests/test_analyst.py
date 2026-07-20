"""Analyst layer tests — gating, budget, and formatting. No API calls."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import analyst  # noqa: E402


def test_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analyst.reset_run_budget()
    assert analyst.analyst_take({"ticker": "SPRB"}) is None


def test_budget_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    analyst.reset_run_budget()
    calls = {"n": 0}

    def fake_take(dossier):
        calls["n"] += 1
        return {"conviction": "LOW"}

    # Exhaust the budget artificially, then verify the gate holds.
    analyst._calls_this_run = analyst.MAX_CALLS_PER_RUN
    assert analyst.analyst_take({"ticker": "SPRB"}) is None


def test_build_dossier_shape():
    d = analyst.build_dossier(
        ticker="SPRB", company="Spruce-pattern biotech", lane_name="Biotech",
        bucket="DEEP_DIVE", thesis={"why_now": "PDUFA in 30d"},
        axes={"opportunity": 80}, red_flags=[], mechanics={"float": 4e6},
        catalysts=[{"date": "2026-09-12"}], changes=["score ↑"],
    )
    assert d["ticker"] == "SPRB"
    assert d["upcoming_catalysts"] == [{"date": "2026-09-12"}]
    assert d["changes_since_last_checkup"] == ["score ↑"]
    assert d["recent_signals"] == []


def test_format_take_lines():
    take = {
        "conviction": "MEDIUM",
        "bull_case": "Tiny float into a dated PDUFA.",
        "bear_case": "Two months of cash — dilution before the event.",
        "dot_connections": ["Same reviewer division approved a rival in March."],
        "what_would_i_verify": ["Read the latest 10-Q cash position",
                                "Confirm PDUFA date in the FDA calendar"],
    }
    lines = analyst.format_take_lines(take)
    text = "\n".join(lines)
    assert "MEDIUM conviction" in text
    assert "Bull:" in text and "Bear:" in text
    assert "🔗" in text
    assert "Verify:" in text
