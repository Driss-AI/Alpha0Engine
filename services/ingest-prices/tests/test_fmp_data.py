"""FMP is the source that finally gives the float lens something to read.

These tests pin the two things that actually matter: that a record carries real
volume through to the caller in the shape the rest of the pipeline expects, and
that a float number is either genuine or absent — never a stand-in.
"""
from datetime import date

import pytest

import fmp_data
from fmp_data import _quote_record, fetch_fmp_float, fetch_fmp_quotes, is_configured


@pytest.fixture(autouse=True)
def _no_key_by_default(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)


class TestKeylessSafety:
    """Without a key the engine must fall through, not crash."""

    def test_not_configured_without_key(self):
        assert is_configured() is False

    def test_quotes_return_empty(self):
        assert fetch_fmp_quotes(["SPRB", "URGN"]) == {}

    def test_float_returns_empty(self):
        assert fetch_fmp_float(["SPRB"]) == {}

    def test_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("FMP_API_KEY", "abc123")
        assert is_configured() is True


class TestQuoteRecord:
    TODAY = date(2026, 7, 24)

    def test_carries_real_volume(self):
        """The whole point: Finnhub returned volume=None, FMP does not."""
        rec = _quote_record({
            "symbol": "SPRB", "price": 3.42, "volume": 1_250_000,
            "avgVolume": 800_000, "open": 3.10, "dayHigh": 3.55,
            "dayLow": 3.05, "changePercentage": 9.62,
        }, self.TODAY)
        assert rec["ticker"] == "SPRB"
        assert rec["close"] == 3.42
        assert rec["volume"] == 1_250_000
        assert rec["avg_volume_30d"] == 800_000
        assert rec["change_pct"] == pytest.approx(0.0962)
        assert rec["is_penny"] is True      # sub-$5 — in the hunting range

    def test_alternate_percent_key_is_accepted(self):
        """FMP has shipped both spellings across API versions."""
        rec = _quote_record({"symbol": "X", "price": 10.0,
                             "changesPercentage": -4.0}, self.TODAY)
        assert rec["change_pct"] == pytest.approx(-0.04)

    def test_row_without_a_price_is_dropped(self):
        assert _quote_record({"symbol": "DEAD", "price": 0}, self.TODAY) is None
        assert _quote_record({"symbol": "", "price": 5.0}, self.TODAY) is None

    def test_missing_volume_is_none_not_zero(self):
        """A missing volume must read as unknown, not as 'no shares traded'."""
        rec = _quote_record({"symbol": "X", "price": 5.0}, self.TODAY)
        assert rec["volume"] is None
        assert rec["avg_volume_30d"] is None

    def test_expensive_stock_is_not_flagged_micro(self):
        rec = _quote_record({"symbol": "BRK", "price": 640000.0}, self.TODAY)
        assert rec["is_penny"] is False
        assert rec["is_micro"] is False


class TestFloatIsGenuineOrAbsent:
    """A wrong float is worse than no float — it silently mis-scores lens 4."""

    def _fake_float_response(self, monkeypatch, payload):
        class _Resp:
            status_code = 200

            def json(self):
                return payload

        class _Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, *a, **k):
                return _Resp()

        monkeypatch.setenv("FMP_API_KEY", "abc123")
        monkeypatch.setattr(fmp_data.httpx, "Client", _Client)
        monkeypatch.setattr(fmp_data.time, "sleep", lambda *_: None)

    def test_real_float_is_captured(self, monkeypatch):
        self._fake_float_response(monkeypatch, [{
            "symbol": "SPRB", "floatShares": 12_400_000,
            "outstandingShares": 41_000_000, "freeFloat": 30.2,
        }])
        out = fetch_fmp_float(["SPRB"])
        assert out["SPRB"]["float_shares"] == 12_400_000
        assert out["SPRB"]["shares_outstanding"] == 41_000_000

    def test_shares_outstanding_is_never_used_as_float(self, monkeypatch):
        """Float absent → report nothing, don't substitute the bigger number."""
        self._fake_float_response(monkeypatch, [{
            "symbol": "SPRB", "outstandingShares": 41_000_000, "freeFloat": 30.2,
        }])
        assert fetch_fmp_float(["SPRB"]) == {}

    def test_percentage_free_float_is_not_mistaken_for_shares(self, monkeypatch):
        """`freeFloat` is a percent; treating 30.2 as a share count is nonsense."""
        self._fake_float_response(monkeypatch, [{"symbol": "SPRB", "freeFloat": 30.2}])
        assert fetch_fmp_float(["SPRB"]) == {}
