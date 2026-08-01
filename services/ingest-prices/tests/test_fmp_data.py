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


class _ScriptedClient:
    """httpx.Client stub that replays a fixed list of (status, body) pairs.

    The last entry repeats, so a test can say "then 429 forever" without
    knowing how many calls the code under test will make.
    """

    calls: list = []
    script: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **k):
        i = min(len(type(self).calls), len(type(self).script) - 1)
        status, body = type(self).script[i]
        type(self).calls.append(params or {})

        class _Resp:
            status_code = status
            text = str(body)

            def json(self):
                return body

        return _Resp()


@pytest.fixture
def scripted(monkeypatch):
    """Install the scripted client and make sleeps free."""
    def _install(script):
        _ScriptedClient.calls = []
        _ScriptedClient.script = script
        monkeypatch.setenv("FMP_API_KEY", "abc123")
        monkeypatch.setattr(fmp_data.httpx, "Client", _ScriptedClient)
        monkeypatch.setattr(fmp_data.time, "sleep", lambda *_: None)
        return _ScriptedClient
    return _install


class TestRateLimitIsBounded:
    """A spent quota must end the phase, not stall the pipeline.

    A 20s sleep per ticker across a 1797-name float list is ~10 hours; the run
    that exposed this was killed at the 90-minute pipeline timeout with every
    downstream step skipped.
    """

    LIMIT = (429, {"Error Message": "Limit Reach . Please upgrade your plan"})

    def test_float_gives_up_after_bounded_retries(self, scripted):
        client = scripted([self.LIMIT])
        assert fetch_fmp_float(["AAA", "BBB", "CCC"]) == {}
        # One ticker's worth of retries, then the phase stops — the second and
        # third tickers are never attempted.
        assert len(client.calls) == fmp_data.MAX_RATE_LIMIT_RETRIES + 1

    def test_quotes_give_up_after_bounded_retries(self, scripted):
        client = scripted([self.LIMIT])
        assert fetch_fmp_quotes(["AAA", "BBB"]) == {}
        assert len(client.calls) == fmp_data.MAX_RATE_LIMIT_RETRIES + 1

    def test_a_transient_429_is_retried_then_succeeds(self, scripted):
        """A per-minute burst is worth waiting out — only a spent quota is not."""
        scripted([
            self.LIMIT,
            (200, [{"symbol": "SPRB", "floatShares": 12_400_000,
                    "outstandingShares": 41_000_000}]),
        ])
        out = fetch_fmp_float(["SPRB"])
        assert out["SPRB"]["float_shares"] == 12_400_000


class TestPlanRejectionStopsImmediately:
    """402/401/403 will not change within a run; asking 91 more times is waste."""

    def test_payment_required_aborts_on_the_first_batch(self, scripted):
        client = scripted([
            (402, {"Error Message": "Special Endpoint : Please upgrade your plan"}),
        ])
        tickers = [f"T{i}" for i in range(fmp_data.QUOTE_BATCH * 3)]
        assert fetch_fmp_quotes(tickers) == {}
        assert len(client.calls) == 1

    def test_rejected_key_aborts_float_immediately(self, scripted):
        client = scripted([(401, {"Error Message": "Invalid API KEY."})])
        assert fetch_fmp_float(["AAA", "BBB", "CCC"]) == {}
        assert len(client.calls) == 1

    def test_a_one_off_server_error_does_not_abort_the_phase(self, scripted):
        """500 is not terminal — the next batch still gets its chance."""
        scripted([
            (500, {"error": "boom"}),
            (200, [{"symbol": "SPRB", "price": 3.42, "volume": 1_000}]),
        ])
        out = fetch_fmp_quotes([f"T{i}" for i in range(fmp_data.QUOTE_BATCH + 1)])
        assert "SPRB" in out
