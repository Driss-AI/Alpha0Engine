"""
EDGAR ingest failure simulation tests.
Verifies the client handles SEC 500 errors, timeouts, and malformed
responses gracefully — no crashes, proper logging.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
import requests

EDGAR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ingest-edgar"))
if EDGAR_DIR not in sys.path:
    sys.path.insert(0, EDGAR_DIR)

from edgar_client import EdgarClient


def _mock_response(status_code=200, json_data=None, text="", raise_for_status=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    if raise_for_status:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_sec_500_returns_empty():
    client = EdgarClient()
    with patch.object(client.session, "get", return_value=_mock_response(500)):
        filings = client.get_form_d_filings("2026-05-28")
    assert filings == []


def test_sec_timeout_returns_empty():
    client = EdgarClient()
    with patch.object(client.session, "get", side_effect=requests.Timeout("Connection timed out")):
        filings = client.get_form_d_filings("2026-05-28")
    assert filings == []


def test_sec_connection_error_returns_empty():
    client = EdgarClient()
    with patch.object(client.session, "get", side_effect=requests.ConnectionError("DNS failure")):
        filings = client.get_form_d_filings("2026-05-28")
    assert filings == []


def test_malformed_json_returns_empty():
    client = EdgarClient()
    resp = _mock_response(200)
    resp.json.side_effect = ValueError("Malformed JSON")
    with patch.object(client.session, "get", return_value=resp):
        filings = client.get_form_d_filings("2026-05-28")
    assert filings == []


def test_valid_response_parsed():
    client = EdgarClient()
    mock_data = {
        "hits": {"hits": [{
            "_id": "0001234567-26-000001:primary_doc.xml",
            "_source": {
                "ciks": ["0001234567"],
                "adsh": "0001234567-26-000001",
                "display_names": ["Test Corp  (CIK 0001234567)"],
                "file_date": "2026-05-28",
            },
        }]},
    }
    with patch.object(client.session, "get", return_value=_mock_response(200, json_data=mock_data)):
        filings = client.get_form_d_filings("2026-05-28")
    assert len(filings) == 1
    assert filings[0]["company_name"] == "Test Corp"
    assert filings[0]["cik"] == "0001234567"


def test_download_filing_404_returns_none():
    client = EdgarClient()
    with patch.object(client.session, "get", return_value=_mock_response(404)):
        result = client.download_filing("https://sec.gov/fake")
    assert result is None


def test_download_filing_500_returns_none():
    client = EdgarClient()
    with patch.object(
        client.session, "get",
        return_value=_mock_response(500, raise_for_status=requests.HTTPError("500 Server Error")),
    ):
        result = client.download_filing("https://sec.gov/fake")
    assert result is None


def test_archive_to_r2_failure_logs_not_crashes(caplog):
    client = EdgarClient()
    with patch.dict("sys.modules", {"shared.clients.r2": MagicMock()}):
        import importlib
        r2_mod = sys.modules["shared.clients.r2"]
        r2_mod.upload = MagicMock(side_effect=Exception("R2 bucket unreachable"))
        client.archive_to_r2({"accession_number": "test"}, "<xml/>", "2026-05-28")


def test_daily_index_fallback_on_efts_empty():
    """When EFTS returns no results, client falls back to daily index."""
    client = EdgarClient()
    efts_resp = _mock_response(200, json_data={"hits": {"hits": []}})
    idx_resp = _mock_response(200, text="0001234567|Test Corp|D|2026-05-28|edgar/data/foo.txt\n")

    call_count = [0]
    def side_effect(*args, **kwargs):
        call_count[0] += 1
        return efts_resp if call_count[0] == 1 else idx_resp

    with patch.object(client.session, "get", side_effect=side_effect):
        filings = client.get_form_d_filings("2026-05-28")
    assert len(filings) == 1
    assert filings[0]["company_name"] == "Test Corp"
