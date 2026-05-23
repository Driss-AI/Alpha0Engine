"""Tests for composite risk engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from risk_engine import compute_risk_score


def test_low_risk():
    hype = {"hype_score": 0.1, "substance_score": 0.8, "hype_gap": -0.7, "hype_flag": False, "patterns": []}
    illiq = {"illiquidity_score": 0.1, "signal_concentration": 0.2, "illiquidity_flag": False, "flags": []}
    result = compute_risk_score(hype, illiq, entity_signal_count=50, sector_avg_signals=20, sector_entity_count=5)
    assert result["risk_tier"] == "GREEN"
    assert result["risk_score"] < 0.25


def test_high_risk():
    hype = {"hype_score": 0.9, "substance_score": 0.1, "hype_gap": 0.8, "hype_flag": True,
            "patterns": ["VAPORWARE_RISK"]}
    illiq = {"illiquidity_score": 0.8, "signal_concentration": 0.9, "illiquidity_flag": True,
             "flags": ["RUNWAY_CRITICAL"]}
    result = compute_risk_score(hype, illiq, entity_signal_count=5, sector_avg_signals=50, sector_entity_count=25)
    assert result["risk_tier"] == "RED"
    assert result["risk_score"] > 0.65


def test_moderate_risk():
    hype = {"hype_score": 0.4, "substance_score": 0.3, "hype_gap": 0.1, "hype_flag": False, "patterns": []}
    illiq = {"illiquidity_score": 0.4, "signal_concentration": 0.5, "illiquidity_flag": False, "flags": []}
    result = compute_risk_score(hype, illiq, entity_signal_count=15, sector_avg_signals=20, sector_entity_count=8)
    assert result["risk_tier"] in ("YELLOW", "ORANGE")


def test_risk_flags_populated():
    hype = {"hype_score": 0.9, "substance_score": 0.1, "hype_gap": 0.8, "hype_flag": True,
            "patterns": ["VAPORWARE_RISK"]}
    illiq = {"illiquidity_score": 0.8, "signal_concentration": 0.5, "illiquidity_flag": True,
             "flags": ["RUNWAY_CRITICAL"]}
    result = compute_risk_score(hype, illiq)
    assert "hype" in result["risk_flags"]
    assert "illiquidity" in result["risk_flags"]
