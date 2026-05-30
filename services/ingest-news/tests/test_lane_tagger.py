"""Tests for news lane tagging (Sprint 8.5)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lane_tagger import tag_news_lanes


def test_tags_ai_infra_news():
    tags = tag_news_lanes(
        "DataCo signs 300MW power purchase agreement",
        "The data center operator signed a PPA to supply its hyperscaler GPU clusters.",
    )
    ai = next((t for t in tags if t["lane_id"] == "L1_AI_INFRA"), None)
    assert ai is not None
    assert ai["high_signal"] is True
    assert "power" in ai["bottlenecks"] or "data_center" in ai["bottlenecks"]


def test_tags_biotech_news():
    tags = tag_news_lanes(
        "BioCo announces positive Phase 3 readout",
        "Topline data met the primary endpoint; PDUFA date set.",
    )
    bio = next((t for t in tags if t["lane_id"] == "L2_BIOTECH"), None)
    assert bio is not None
    assert bio["high_signal"] is True


def test_irrelevant_news_no_tags():
    tags = tag_news_lanes("Retailer reports holiday sales", "Same-store sales rose 3%.")
    assert tags == []


def test_high_signal_requires_phrase():
    # Mentions a lane keyword but no high-signal catalyst phrase
    tags = tag_news_lanes("Company discusses data center strategy", "General commentary on cloud.")
    ai = next((t for t in tags if t["lane_id"] == "L1_AI_INFRA"), None)
    if ai:
        assert ai["high_signal"] is False
