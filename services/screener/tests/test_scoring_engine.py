"""Tests for composite scoring engine."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scoring_engine import compute_fundamental_score


def test_moat_only_scoring():
    moat = {"moat_score": 0.75}
    result = compute_fundamental_score(moat)
    assert result["fundamental_score"] == 0.75
    assert result["screening_tier"] == "A"


def test_public_company_scoring():
    moat = {"moat_score": 0.6}
    public = {
        "gross_margin": 0.78,
        "gross_margin_velocity": 0.03,
        "revenue_growth_yoy": 0.55,
        "cash_runway_months": 30,
        "rule_of_40": 50,
        "rd_expense": 500_000_000,
        "market_cap_usd": 2_000_000_000,
    }
    result = compute_fundamental_score(moat, public_metrics=public, entity_type="public")
    assert 0.5 < result["fundamental_score"] <= 1.0
    assert result["screening_tier"] in ("S", "A", "B")


def test_private_company_scoring():
    moat = {"moat_score": 0.5}
    private = {
        "total_raised": 80_000_000,
        "secondary_vs_primary": 15.0,
        "estimated_runway_months": 20,
    }
    result = compute_fundamental_score(moat, private_metrics=private, entity_type="private")
    assert 0.3 < result["fundamental_score"] <= 1.0


def test_tier_assignment():
    assert compute_fundamental_score({"moat_score": 0.9})["screening_tier"] == "S"
    assert compute_fundamental_score({"moat_score": 0.7})["screening_tier"] == "A"
    assert compute_fundamental_score({"moat_score": 0.5})["screening_tier"] == "B"
    assert compute_fundamental_score({"moat_score": 0.3})["screening_tier"] == "C"
    assert compute_fundamental_score({"moat_score": 0.1})["screening_tier"] == "D"


def test_d_tier_weak():
    moat = {"moat_score": 0.05}
    result = compute_fundamental_score(moat)
    assert result["screening_tier"] == "D"
    assert result["fundamental_score"] < 0.25
