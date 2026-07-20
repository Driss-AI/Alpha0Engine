"""Tests for composite risk engine."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from risk_engine import compute_risk_score, detect_red_flags


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


# ── Sprint 7.6: lane-specific red flags ─────────────────────────────────────

def test_red_flags_critical_forces_flag():
    r = detect_red_flags(
        lane_id="L1_AI_INFRA", market_cap_usd=2e9,
        extra_flags=["going_concern", "single_hyperscaler_dependency"],
    )
    assert r["has_critical"] is True
    assert "going_concern" in r["critical_flags"]
    # lane vocabulary surfaces the lane-specific flag even when it's not critical
    assert "single_hyperscaler_dependency" in r["lane_flag_vocabulary"]


def test_red_flags_mechanical_detectors():
    r = detect_red_flags(
        lane_id="L2_BIOTECH", market_cap_usd=10e6,
        volume_ratio=0.1, has_catalyst_date=False,
    )
    assert "market_cap_under_15m" in r["critical_flags"]
    assert "no_volume" in r["red_flags"]
    assert "no_catalyst_date" in r["red_flags"]
    assert "trial_failure" in r["lane_flag_vocabulary"]


def test_red_flags_insider_selling_cluster():
    signals = [
        {"signal_type": "insider_sell"},
        {"signal_type": "insider_sell_cluster"},
    ]
    r = detect_red_flags(lane_id="L1_AI_INFRA", market_cap_usd=1e9, signals=signals)
    assert "insider_selling_cluster" in r["red_flags"]


def test_red_flags_clean_company():
    r = detect_red_flags(
        lane_id="L1_AI_INFRA", market_cap_usd=5e9,
        volume_ratio=1.5, has_catalyst_date=True,
    )
    assert r["red_flags"] == []
    assert r["has_critical"] is False


def test_red_flags_lane_vocabulary_differs_by_lane():
    ai = detect_red_flags(lane_id="L1_AI_INFRA", market_cap_usd=2e9)
    bio = detect_red_flags(lane_id="L2_BIOTECH", market_cap_usd=2e8)
    assert "single_hyperscaler_dependency" in ai["lane_flag_vocabulary"]
    assert "single_hyperscaler_dependency" not in bio["lane_flag_vocabulary"]
    assert "trial_failure" in bio["lane_flag_vocabulary"]
