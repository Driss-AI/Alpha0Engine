"""Sentinel change-detection tests — the pure core, no DB."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sentinel import detect_changes, format_checkup  # noqa: E402


BASE = {
    "composite_score": 0.62,
    "bucket": "DEEP_DIVE",
    "red_flags": ["no_catalyst_date"],
    "critical_flags": [],
    "catalyst_date": None,
    "signal_count": 10,
}


def test_no_change_is_silent():
    diff = detect_changes(BASE, dict(BASE))
    assert diff["changes"] == []
    assert not diff["escalate"]
    assert not diff["material"]


def test_new_critical_flag_escalates():
    curr = dict(BASE, red_flags=["no_catalyst_date", "active_atm"],
                critical_flags=["active_atm"])
    diff = detect_changes(BASE, curr)
    assert diff["escalate"]
    assert diff["material"]
    assert any("CRITICAL" in c and "active_atm" in c for c in diff["changes"])


def test_bucket_drop_to_no_touch_escalates():
    curr = dict(BASE, bucket="NO_TOUCH")
    diff = detect_changes(BASE, curr)
    assert diff["escalate"]
    assert any("DEEP_DIVE → NO_TOUCH" in c for c in diff["changes"])


def test_score_move_reported_and_material_threshold():
    small = dict(BASE, composite_score=0.64)   # +0.02 — below both thresholds
    assert detect_changes(BASE, small)["changes"] == []

    medium = dict(BASE, composite_score=0.68)  # +0.06 — reported, not material
    diff = detect_changes(BASE, medium)
    assert any("score ↑" in c for c in diff["changes"])
    assert not diff["material"]

    big = dict(BASE, composite_score=0.74)     # +0.12 — material
    assert detect_changes(BASE, big)["material"]


def test_catalyst_dated_and_moved():
    dated = dict(BASE, catalyst_date="2026-09-12")
    diff = detect_changes(BASE, dated)
    assert any("catalyst dated: 2026-09-12" in c for c in diff["changes"])

    moved = dict(BASE, catalyst_date="2026-10-01")
    diff2 = detect_changes(dated, moved)
    assert any("catalyst moved 2026-09-12 → 2026-10-01" in c for c in diff2["changes"])


def test_new_signals_counted():
    curr = dict(BASE, signal_count=13)
    diff = detect_changes(BASE, curr)
    assert any("3 new signal(s)" in c for c in diff["changes"])


def test_first_checkup_against_empty_state_changes():
    diff = detect_changes({}, BASE)
    # score move from nothing isn't computed; new signals + flags are
    assert any("new signal" in c for c in diff["changes"])


def test_format_checkup_escalation_header():
    msg = format_checkup("SPRB", ["🚨 CRITICAL: active_atm"],
                         escalate=True, bucket="NO_TOUCH", catalyst_line=None)
    assert msg.startswith("🔔 EXIT ALARM — SPRB")
    assert "NO_TOUCH" in msg


def test_format_checkup_regular():
    msg = format_checkup("SPRB", ["score ↑ 0.620 → 0.700"],
                         escalate=False, bucket="DEEP_DIVE",
                         catalyst_line="📅 PDUFA in 23d (2026-08-11)",
                         take_lines=["🧠 Analyst take (HIGH conviction)"])
    assert msg.startswith("🩺 Checkup — SPRB")
    assert "PDUFA in 23d" in msg
    assert "Analyst take" in msg
