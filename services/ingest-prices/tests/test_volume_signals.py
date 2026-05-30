"""Tests for volume awakening detection (Sprint 8.8)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from volume_signals import detect_volume_signals, volume_ratio


def test_volume_ratio():
    assert volume_ratio(300, 100) == 3.0
    assert volume_ratio(None, 100) is None
    assert volume_ratio(100, 0) is None
    assert volume_ratio(100, None) is None


def test_volume_awakening_fires_at_2x():
    sigs = detect_volume_signals({"volume": 250, "avg_volume_30d": 100})
    types = [s["signal_type"] for s in sigs]
    assert "volume_awakening" in types
    awakening = next(s for s in sigs if s["signal_type"] == "volume_awakening")
    assert awakening["detail"]["volume_ratio"] == 2.5
    assert 0.5 <= awakening["value"] <= 1.0


def test_no_awakening_below_2x():
    sigs = detect_volume_signals({"volume": 150, "avg_volume_30d": 100})
    assert [s["signal_type"] for s in sigs] == []


def test_price_breakout_requires_move_and_volume():
    sigs = detect_volume_signals({
        "volume": 200, "avg_volume_30d": 100,   # 2x volume
        "change_20d_pct": 0.30,                  # +30%
    })
    types = [s["signal_type"] for s in sigs]
    assert "volume_awakening" in types
    assert "price_breakout" in types


def test_no_breakout_without_volume():
    sigs = detect_volume_signals({
        "volume": 110, "avg_volume_30d": 100,   # only 1.1x
        "change_20d_pct": 0.30,
    })
    assert "price_breakout" not in [s["signal_type"] for s in sigs]


def test_empty_record():
    assert detect_volume_signals({}) == []
