"""
Tests — 8-K Filing Classifier
================================
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from filing_classifier import (
    extract_items, classify_catalyst, compute_signal_value,
    is_catalyst_filing,
)


class TestItemExtraction:
    def test_single_item(self):
        text = "Item 7.01 Regulation FD Disclosure"
        assert "7.01" in extract_items(text)

    def test_multiple_items(self):
        text = "Item 1.01 Entry into Agreement\nItem 8.01 Other Events\nItem 9.01 Exhibits"
        items = extract_items(text)
        assert "1.01" in items
        assert "8.01" in items
        assert "9.01" in items

    def test_no_items(self):
        assert extract_items("Random text with no items") == []


class TestCatalystClassification:
    def test_fda_approval(self):
        text = "The company announced FDA approval of its new drug application"
        result = classify_catalyst(text)
        assert result["catalyst_type"] == "fda_approval"
        assert result["confidence"] > 0

    def test_clinical_trial(self):
        text = "Positive topline data from Phase 3 pivotal trial showed statistically significant results"
        result = classify_catalyst(text)
        assert result["catalyst_type"] == "clinical_trial_data"

    def test_merger(self):
        text = "Company entered into a definitive agreement to acquire XYZ Corp"
        result = classify_catalyst(text)
        assert result["catalyst_type"] == "merger_acquisition"

    def test_contract(self):
        text = "Received contract award from the Department of Defense for task order"
        result = classify_catalyst(text)
        assert result["catalyst_type"] == "contract_award"

    def test_partnership(self):
        text = "Announced strategic partnership and licensing agreement for co-development"
        result = classify_catalyst(text)
        assert result["catalyst_type"] == "partnership"

    def test_no_catalyst(self):
        text = "Quarterly financial results for the period ending March 2026"
        result = classify_catalyst(text)
        assert result["catalyst_type"] is None

    def test_high_confidence(self):
        text = "FDA approved the NDA. PDUFA target met. Breakthrough therapy designation confirmed."
        result = classify_catalyst(text)
        assert result["confidence"] >= 0.9


class TestSignalValue:
    def test_fda_high_value(self):
        items = ["7.01", "8.01"]
        catalyst = {"catalyst_type": "fda_approval", "confidence": 0.8}
        value = compute_signal_value(items, catalyst)
        assert value >= 0.7

    def test_offering_low_value(self):
        items = ["8.01"]
        catalyst = {"catalyst_type": "offering", "confidence": 0.5}
        value = compute_signal_value(items, catalyst)
        assert value < 0.3

    def test_no_catalyst_moderate(self):
        items = ["7.01"]
        catalyst = {"catalyst_type": None, "confidence": 0}
        value = compute_signal_value(items, catalyst)
        assert 0.2 <= value <= 0.5


class TestCatalystFiltering:
    def test_significant_item(self):
        assert is_catalyst_filing(["7.01"], {"catalyst_type": None}) is True

    def test_routine_only(self):
        assert is_catalyst_filing(["2.02", "9.01"], {"catalyst_type": None}) is False

    def test_catalyst_overrides(self):
        """Even routine items + catalyst = keep."""
        assert is_catalyst_filing(["2.02"], {"catalyst_type": "fda_approval"}) is True

    def test_empty(self):
        assert is_catalyst_filing([], {"catalyst_type": None}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── Sprint 8.3: lane-aware classification ───────────────────────────────────
from filing_classifier import lane_for_catalyst, red_flags_from_classification


class TestLaneAwareClassification:
    def test_classifies_ppa_as_ai_infra(self):
        text = ("Item 1.01 Entry into a Material Definitive Agreement. The Company "
                "entered into a 200 megawatt power purchase agreement (PPA) with a "
                "hyperscale data center operator.")
        cat = classify_catalyst(text)
        assert cat["catalyst_type"] in ("ppa_signed", "hyperscaler_contract", "data_center_lease")
        lane = lane_for_catalyst(cat["catalyst_type"])
        assert lane["lane_id"] == "L1_AI_INFRA"
        assert "bottleneck" in lane

    def test_classifies_gpu_order_as_ai_infra(self):
        text = "The Company placed an order for NVIDIA H100 GPUs for accelerated computing."
        cat = classify_catalyst(text)
        assert cat["catalyst_type"] == "gpu_order"
        assert lane_for_catalyst("gpu_order")["lane_id"] == "L1_AI_INFRA"

    def test_classifies_fda_as_biotech(self):
        text = "The FDA approved the Company's new drug application (NDA approval)."
        cat = classify_catalyst(text)
        assert cat["catalyst_type"] == "fda_approval"
        assert lane_for_catalyst("fda_approval")["lane_id"] == "L2_BIOTECH"

    def test_lane_agnostic_returns_empty(self):
        assert lane_for_catalyst("merger_acquisition") == {}
        assert lane_for_catalyst(None) == {}

    def test_going_concern_red_flag(self):
        text = ("Item 8.01. The Company's financial statements include a going concern "
                "qualification; substantial doubt about its ability to continue.")
        cat = classify_catalyst(text)
        flags = red_flags_from_classification(cat)
        assert "going_concern" in flags

    def test_offering_red_flag(self):
        text = "Item 1.01 The Company entered into an at-the-market offering and shelf registration."
        cat = classify_catalyst(text)
        flags = red_flags_from_classification(cat)
        assert "recent_dilutive_offering" in flags

    def test_clean_contract_no_red_flags(self):
        text = "Item 1.01 The Company signed a strategic partnership and licensing agreement."
        cat = classify_catalyst(text)
        assert red_flags_from_classification(cat) == []
