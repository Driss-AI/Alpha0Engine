"""Tests for the mandatory alert template (Sprint 9.6)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from alert_formatter import format_alert, build_dedupe_key


THESIS = {
    "megatrend": "AI training + inference explosion",
    "bottleneck": "power",
    "exposure": "Bloom Energy sits on the power bottleneck of ai infrastructure.",
    "evidence": [
        {"summary": "200MW PPA signed", "source_url": "https://sec.gov/x"},
        {"summary": "Q1 capex inflection", "source_url": "https://sec.gov/y"},
    ],
    "why_now": "ppa_signed dated 2026-07-15; volume 2.3x its 30-day average.",
    "catalyst_type": "ppa_signed",
    "catalyst_date": "2026-07-15",
}
AXES = {"opportunity": 89.7, "risk": 20.0, "timing": 88.0, "confidence": 88.0, "tradability": 70.0}


def test_template_has_all_mandatory_fields():
    msg = format_alert(
        ticker="BE", company="Bloom Energy", lane_name="AI Infrastructure",
        thesis=THESIS, axes=AXES, bucket="SETUP_READY", red_flags=[],
        mechanics={"short_pct_float": 0.25, "volume_ratio": 2.3},
    )
    for required in ["ALERT: BE", "Lane:", "Megatrend:", "Bottleneck:", "Exposure:",
                     "Evidence:", "Catalyst:", "Mechanics:", "Scores:", "Red flags:",
                     "Why now:", "Action:"]:
        assert required in msg, f"missing mandatory field: {required}"


def test_memo_summary_embedded():
    """Sprint 13.3: the memo highlight (invalidation + first check) is embedded."""
    msg = format_alert(
        ticker="BE", company="Bloom Energy", lane_name="AI Infrastructure",
        thesis=THESIS, axes=AXES, bucket="SETUP_READY", red_flags=[],
        mechanics={"short_pct_float": 0.25, "volume_ratio": 2.3},
        memo_summary=["Would invalidate: catalyst slips", "Check first: float on a 2nd source"],
    )
    assert "Would invalidate: catalyst slips" in msg
    assert "Check first: float on a 2nd source" in msg
    # summary sits above the action line
    assert msg.index("Would invalidate:") < msg.index("Action:")


def test_evidence_urls_present():
    msg = format_alert(
        ticker="BE", company="Bloom Energy", lane_name="AI Infrastructure",
        thesis=THESIS, axes=AXES, bucket="DEEP_DIVE", red_flags=[],
    )
    assert "https://sec.gov/x" in msg
    assert "200MW PPA signed" in msg


def test_action_never_says_buy():
    msg = format_alert(
        ticker="BE", company="Bloom Energy", lane_name="AI Infrastructure",
        thesis=THESIS, axes=AXES, bucket="SETUP_READY", red_flags=[],
    )
    assert "do not buy blind" in msg
    assert "BUY NOW" not in msg.upper().replace("DO NOT BUY", "")


def test_red_flags_rendered():
    msg = format_alert(
        ticker="XYZ", company="XYZ Corp", lane_name="Biotech Catalysts",
        thesis=THESIS, axes=AXES, bucket="DEEP_DIVE",
        red_flags=["going_concern", "recent_dilutive_offering"],
    )
    assert "going_concern" in msg


def test_no_dated_catalyst_shown_explicitly():
    t = {**THESIS, "catalyst_type": None, "catalyst_date": None}
    msg = format_alert(
        ticker="BE", company="Bloom Energy", lane_name="AI Infrastructure",
        thesis=t, axes=AXES, bucket="DEEP_DIVE", red_flags=[],
    )
    assert "Catalyst: none dated" in msg


def test_dedupe_key():
    assert build_dedupe_key("BE", "L1_AI_INFRA", "SETUP_READY") == "BE:L1_AI_INFRA:SETUP_READY"
    assert build_dedupe_key("BE", None, "DEEP_DIVE") == "BE:nolane:DEEP_DIVE"
