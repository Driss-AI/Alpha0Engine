"""Unit tests for the FDA client parser (Sprint 8.2)."""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fda_client import parse_drugsfda_result, _parse_openfda_date


def test_parse_openfda_date():
    assert _parse_openfda_date("20260115") == date(2026, 1, 15)
    assert _parse_openfda_date(None) is None
    assert _parse_openfda_date("garbage") is None


def test_parse_approved_submission():
    result = {
        "application_number": "NDA123456",
        "sponsor_name": "Acme Therapeutics Inc",
        "products": [{"brand_name": "WONDERDRUG", "dosage_form": "TABLET"}],
        "submissions": [
            {"submission_status": "AP", "submission_type": "ORIG",
             "submission_number": "1", "submission_status_date": "20260201"},
        ],
    }
    events = parse_drugsfda_result(result)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "approval"
    assert ev["drug_name"] == "WONDERDRUG"
    assert ev["company"] == "Acme Therapeutics Inc"
    assert ev["event_date"] == date(2026, 2, 1)
    assert ev["status"] == "approved"


def test_skip_non_approved_submissions():
    result = {
        "application_number": "NDA999",
        "sponsor_name": "BioCo",
        "products": [{"brand_name": "DRUGX"}],
        "submissions": [
            {"submission_status": "TA", "submission_status_date": "20260101"},  # tentative
            {"submission_status": "AP", "submission_status_date": "20260301"},  # approved
        ],
    }
    events = parse_drugsfda_result(result)
    assert len(events) == 1
    assert events[0]["event_date"] == date(2026, 3, 1)


def test_handles_missing_products():
    result = {
        "application_number": "NDA000",
        "sponsor_name": "NoProductCo",
        "products": [],
        "submissions": [{"submission_status": "AP", "submission_status_date": "20260101"}],
    }
    events = parse_drugsfda_result(result)
    assert len(events) == 1
    assert events[0]["drug_name"] is None
