"""
Tests — Clinical Trial Ingestion
===================================
Tests for CT.gov API parsing, trial-to-entity matching,
and catalyst proximity computation.
"""
import sys
import os
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trial_matcher import _normalize, _match_score, match_sponsor_to_entities, build_entity_index, match_sponsor_indexed
from ct_client import _parse_ct_date, _extract_study


# ═══════════════════════════════════════════════════════════
# Name Normalization
# ═══════════════════════════════════════════════════════════
class TestNormalization:
    def test_strip_inc(self):
        assert _normalize("Supernus Pharmaceuticals, Inc.") == "supernus"

    def test_strip_corp(self):
        assert _normalize("Acacia Research Corporation") == "acacia research"

    def test_strip_ltd(self):
        assert _normalize("AstraZeneca Ltd") == "astrazeneca"

    def test_lowercase(self):
        assert _normalize("NVIDIA") == "nvidia"

    def test_empty(self):
        assert _normalize("") == ""

    def test_multiple_suffixes(self):
        result = _normalize("BioGen Therapeutics Inc.")
        assert "biogen" in result
        assert "inc" not in result


# ═══════════════════════════════════════════════════════════
# Match Scoring
# ═══════════════════════════════════════════════════════════
class TestMatchScore:
    def test_exact_match(self):
        score = _match_score("Supernus Pharmaceuticals", "Supernus Pharmaceuticals Inc.")
        assert score >= 0.9

    def test_partial_match(self):
        score = _match_score("Acacia Research", "Acacia Research Corporation")
        assert score >= 0.7

    def test_no_match(self):
        score = _match_score("Apple Inc", "Microsoft Corporation")
        assert score < 0.3

    def test_empty(self):
        score = _match_score("", "Test Corp")
        assert score == 0.0

    def test_similar_biotech(self):
        score = _match_score("Moderna, Inc.", "Moderna")
        assert score >= 0.9


# ═══════════════════════════════════════════════════════════
# Entity Matching
# ═══════════════════════════════════════════════════════════
class TestEntityMatching:
    def setup_method(self):
        self.entities = [
            {"id": "1", "name": "Supernus Pharmaceuticals", "ticker": "SUPN"},
            {"id": "2", "name": "Moderna", "ticker": "MRNA"},
            {"id": "3", "name": "Pfizer", "ticker": "PFE"},
            {"id": "4", "name": "Apple", "ticker": "AAPL"},
            {"id": "5", "name": "Acacia Research", "ticker": "ACTG"},
        ]

    def test_match_with_suffix(self):
        result = match_sponsor_to_entities("Supernus Pharmaceuticals, Inc.", self.entities)
        assert result is not None
        assert result["ticker"] == "SUPN"

    def test_match_exact(self):
        result = match_sponsor_to_entities("Moderna", self.entities)
        assert result is not None
        assert result["ticker"] == "MRNA"

    def test_match_pfizer(self):
        result = match_sponsor_to_entities("Pfizer Inc.", self.entities)
        assert result is not None
        assert result["ticker"] == "PFE"

    def test_no_match_threshold(self):
        result = match_sponsor_to_entities("RandomUnknownCompany LLC", self.entities)
        assert result is None

    def test_indexed_match(self):
        index = build_entity_index(self.entities)
        result = match_sponsor_indexed("Moderna, Inc.", index, self.entities)
        assert result is not None
        assert result["ticker"] == "MRNA"


# ═══════════════════════════════════════════════════════════
# Date Parsing
# ═══════════════════════════════════════════════════════════
class TestDateParsing:
    def test_iso_date(self):
        dt = _parse_ct_date("2026-06-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6

    def test_month_only(self):
        dt = _parse_ct_date("2026-06")
        assert dt is not None
        assert dt.year == 2026

    def test_none(self):
        assert _parse_ct_date(None) is None

    def test_empty(self):
        assert _parse_ct_date("") is None


# ═══════════════════════════════════════════════════════════
# Study Extraction
# ═══════════════════════════════════════════════════════════
class TestStudyExtraction:
    def test_extract_basic(self):
        """Test extraction from a minimal CT.gov v2 response."""
        study = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT12345678",
                    "briefTitle": "Study of Drug X in Cancer",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2025-01-15"},
                    "primaryCompletionDateStruct": {"date": "2026-08-01"},
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {
                        "name": "TestPharma Inc.",
                        "class": "INDUSTRY",
                    },
                },
                "designModule": {
                    "phases": ["PHASE3"],
                },
                "conditionsModule": {
                    "conditions": ["Non-Small Cell Lung Cancer"],
                },
                "armsInterventionsModule": {
                    "interventions": [
                        {"name": "Drug X", "type": "DRUG", "description": "Test drug"},
                    ],
                },
            },
        }
        result = _extract_study(study)
        assert result["nct_id"] == "NCT12345678"
        assert result["phase"] == "PHASE3"
        assert result["status"] == "RECRUITING"
        assert result["lead_sponsor"] == "TestPharma Inc."
        assert result["sponsor_class"] == "INDUSTRY"
        assert result["primary_completion_date"] == "2026-08-01"
        assert result["primary_completion_dt"] is not None
        assert result["primary_completion_dt"].year == 2026
        assert len(result["conditions"]) == 1
        assert len(result["interventions"]) == 1

    def test_extract_empty(self):
        """Empty study should not crash."""
        result = _extract_study({})
        assert result["nct_id"] == ""
        assert result["phase"] == ""


# ═══════════════════════════════════════════════════════════
# Catalyst Proximity (from main.py)
# ═══════════════════════════════════════════════════════════
class TestCatalystProximity:
    def test_future_date(self):
        from main import _compute_catalyst_proximity
        trial = {
            "primary_completion_dt": datetime.utcnow() + timedelta(days=45),
        }
        days = _compute_catalyst_proximity(trial)
        assert days is not None
        assert 44 <= days <= 46

    def test_past_date(self):
        from main import _compute_catalyst_proximity
        trial = {
            "primary_completion_dt": datetime.utcnow() - timedelta(days=10),
        }
        days = _compute_catalyst_proximity(trial)
        assert days is not None
        assert days < 0

    def test_no_date(self):
        from main import _compute_catalyst_proximity
        trial = {}
        days = _compute_catalyst_proximity(trial)
        assert days is None

    def test_signal_value_phase3_near(self):
        from main import _compute_signal_value
        trial = {"phase": "PHASE3", "status": "ACTIVE_NOT_RECRUITING"}
        value = _compute_signal_value(trial, proximity_days=25)
        assert value >= 0.9  # Phase 3 + near + active

    def test_signal_value_phase2_far(self):
        from main import _compute_signal_value
        trial = {"phase": "PHASE2", "status": "RECRUITING"}
        value = _compute_signal_value(trial, proximity_days=300)
        assert 0.4 <= value <= 0.6

    def test_catalyst_type_phase3(self):
        from main import _classify_catalyst_type
        assert _classify_catalyst_type({"phase": "PHASE3", "status": "RECRUITING"}) == "fda_pdufa"
        assert _classify_catalyst_type({"phase": "PHASE3", "status": "COMPLETED"}) == "clinical_trial_data"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
