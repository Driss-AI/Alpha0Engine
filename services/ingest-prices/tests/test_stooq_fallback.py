"""Stooq/SEC fallback — parsing and frame-selection tests. No network."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stooq_fallback import _candidate_frames, _parse_stooq_csv  # noqa: E402

CSV = """Symbol,Date,Time,Open,High,Low,Close,Volume
AAPL.US,2026-07-22,22:00:11,255.1,257.9,254.0,256.48,41865400
GME.US,2026-07-22,22:00:11,22.5,23.1,22.3,22.9,3865400
FAKE.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D
"""


def test_parse_stooq_csv_happy_path():
    out = _parse_stooq_csv(CSV)
    assert set(out) == {"AAPL", "GME"}  # FAKE (N/D) dropped
    rec = out["AAPL"]
    assert rec["close"] == 256.48
    assert rec["trade_date"] == date(2026, 7, 22)
    assert rec["volume"] == 41865400
    assert rec["is_penny"] is False
    assert out["GME"]["is_micro"] is True


def test_parse_stooq_csv_garbage_is_ignored():
    assert _parse_stooq_csv("") == {}
    assert _parse_stooq_csv("<html>Exceeded the daily hits limit</html>") == {}
    assert _parse_stooq_csv("Symbol,Date,Time,Open,High,Low,Close,Volume\nBAD,ROW") == {}


def test_candidate_frames_step_back_across_year():
    frames = _candidate_frames(today=date(2026, 2, 10))
    assert frames == ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"]


def test_candidate_frames_mid_year():
    frames = _candidate_frames(today=date(2026, 7, 23))
    assert frames[0] == "CY2026Q3I"
    assert len(frames) == 4


class _FakeResp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Serves CSV only for single-symbol requests, 404 for multi — exercises bisect."""
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        symbols = url.split("?s=")[1].split("&")[0].split(",")
        if len(symbols) > 1:
            return _FakeResp(404, "")
        sym = symbols[0].removesuffix(".us").upper()
        return _FakeResp(200, f"Symbol,Date,Time,Open,High,Low,Close,Volume\n{sym}.US,2026-07-22,22:00:11,1,2,0.5,1.5,100\n")


def test_stooq_url_has_literal_commas_and_bare_h(monkeypatch):
    import stooq_fallback as sf
    monkeypatch.setattr(sf.time, "sleep", lambda s: None)
    client = _FakeClient()
    out = {}
    sf._fetch_batch_with_split(client, ["AAPL", "GME", "SPRB", "XYZ", "ABCD"], out)
    first = client.urls[0]
    assert "%2C" not in first and "aapl.us,gme.us" in first
    assert "&h&e=csv" in first  # bare flag, not h=
    # bisect recovered the singles (batches of >=5 split down to <5 singles served)
    assert "AAPL" in out and out["AAPL"][0]["close"] == 1.5


def test_stooq_probe_failure_short_circuits(monkeypatch):
    import stooq_fallback as sf
    monkeypatch.setattr(sf.time, "sleep", lambda s: None)

    class DeadClient:
        def get(self, url):
            return _FakeResp(404, "")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sf.httpx, "Client", lambda **kw: DeadClient())
    assert sf.fetch_stooq_quotes(["AAPL", "GME"]) == {}


def test_finnhub_quotes_no_key_returns_empty(monkeypatch):
    import finnhub_quotes as fq
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert fq.fetch_finnhub_quotes(["AAPL"]) == {}


def test_finnhub_quotes_parses_and_respects_budget(monkeypatch):
    import finnhub_quotes as fq
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setenv("FINNHUB_QUOTE_BUDGET", "2")
    monkeypatch.setattr(fq.time, "sleep", lambda s: None)
    calls = []

    class FakeClient:
        def get(self, url, params=None):
            calls.append(params["symbol"])
            return _FakeResp(200, "") if False else type(
                "R", (), {"status_code": 200,
                          "json": lambda self: {"c": 4.2, "o": 4.0, "h": 4.5, "l": 3.9, "dp": 5.0}}
            )()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fq.httpx, "Client", lambda **kw: FakeClient())
    out = fq.fetch_finnhub_quotes(["AAA", "BBB", "CCC"])
    assert calls == ["AAA", "BBB"]  # budget of 2 respected
    rec = out["AAA"][0]
    assert rec["close"] == 4.2 and rec["is_penny"] is True
    assert rec["change_pct"] == 0.05


def test_finnhub_profiles_scale_millions(monkeypatch):
    import finnhub_quotes as fq
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr(fq.time, "sleep", lambda s: None)

    class FakeClient:
        def get(self, url, params=None):
            return type("R", (), {"status_code": 200,
                                  "json": lambda self: {"marketCapitalization": 85.2,
                                                        "shareOutstanding": 4.1,
                                                        "name": "Tiny Bio"}})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fq.httpx, "Client", lambda **kw: FakeClient())
    out = fq.fetch_finnhub_profiles(["TINY"])
    assert out["TINY"]["market_cap"] == 85_200_000.0
    assert out["TINY"]["shares_outstanding"] == 4_100_000.0


def test_sec_frames_merge_newest_wins(monkeypatch):
    import stooq_fallback as sf

    frames_served = {
        "CY2026Q3I": {"data": [{"cik": 111, "val": 999.0}]},
        "CY2026Q2I": {"data": [{"cik": 111, "val": 5.0}, {"cik": 222, "val": 7.0}]},
    }

    def fake_get(url, headers=None, timeout=None):
        for frame, payload in frames_served.items():
            if frame in url:
                return type("R", (), {"status_code": 200, "json": lambda self, p=payload: p})()
        return type("R", (), {"status_code": 404, "json": lambda self: {}})()

    monkeypatch.setattr(sf.httpx, "get", fake_get)
    monkeypatch.setattr(sf, "_candidate_frames",
                        lambda today=None: ["CY2026Q3I", "CY2026Q2I", "CY2026Q1I", "CY2025Q4I"])
    out = sf.fetch_sec_shares_outstanding()
    assert out["111"] == 999.0  # newest frame wins
    assert out["222"] == 7.0    # older frame still merged in
