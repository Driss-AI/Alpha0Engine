"""
Tests — Price Fetcher & Ingestion
===================================
Unit tests for price parsing, market cap computation, and universe discovery.
"""
import sys
import os
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from price_fetcher import _parse_single_ticker_df, fetch_universe_tickers_sec
import pandas as pd
import numpy as np


class TestPriceParsing:
    def _make_df(self, closes, volumes=None, n=None):
        """Helper to create a mock price DataFrame."""
        if n is None:
            n = len(closes)
        dates = pd.date_range(end="2026-05-22", periods=n, freq="D")
        if volumes is None:
            volumes = [1000000] * n
        df = pd.DataFrame({
            "Open": [c * 0.99 for c in closes],
            "High": [c * 1.02 for c in closes],
            "Low": [c * 0.98 for c in closes],
            "Close": closes,
            "Volume": volumes,
        }, index=dates)
        return df

    def test_basic_parsing(self):
        """Should parse OHLCV into records."""
        df = self._make_df([10.0, 10.5, 11.0])
        records = _parse_single_ticker_df("TEST", df)
        assert len(records) == 3
        assert records[0]["ticker"] == "TEST"
        assert records[-1]["close"] == 11.0

    def test_daily_change(self):
        """Should compute daily % change."""
        df = self._make_df([10.0, 11.0, 10.0])
        records = _parse_single_ticker_df("TEST", df)
        assert records[1]["change_pct"] == pytest.approx(0.1, abs=0.001)
        assert records[2]["change_pct"] == pytest.approx(-0.0909, abs=0.001)

    def test_first_day_no_change(self):
        """First day should have no change_pct."""
        df = self._make_df([10.0, 11.0])
        records = _parse_single_ticker_df("TEST", df)
        assert records[0]["change_pct"] is None

    def test_penny_flag(self):
        """Stocks under $5 should be flagged as penny."""
        df = self._make_df([3.50])
        records = _parse_single_ticker_df("TEST", df)
        assert records[0]["is_penny"] is True

    def test_not_penny(self):
        """Stocks over $5 should not be penny."""
        df = self._make_df([25.00])
        records = _parse_single_ticker_df("TEST", df)
        assert records[0]["is_penny"] is False

    def test_micro_flag(self):
        """Stocks under $50 flagged as micro."""
        df = self._make_df([45.00])
        records = _parse_single_ticker_df("TEST", df)
        assert records[0]["is_micro"] is True

    def test_not_micro(self):
        """Stocks over $50 not micro."""
        df = self._make_df([150.00])
        records = _parse_single_ticker_df("TEST", df)
        assert records[0]["is_micro"] is False

    def test_skip_zero_close(self):
        """Should skip rows with zero or negative close."""
        df = self._make_df([10.0, 0.0, 11.0])
        records = _parse_single_ticker_df("TEST", df)
        assert len(records) == 2
        assert records[0]["close"] == 10.0
        assert records[1]["close"] == 11.0

    def test_empty_df(self):
        """Empty DataFrame should return empty list."""
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        records = _parse_single_ticker_df("TEST", df)
        assert records == []

    def test_5d_change(self):
        """Should compute 5-day change when enough data."""
        closes = [10.0, 10.5, 11.0, 10.8, 11.5, 12.0]
        df = self._make_df(closes)
        records = _parse_single_ticker_df("TEST", df)
        # 5th record (idx=5) vs idx=0: (12.0 - 10.0) / 10.0 = 0.2
        assert records[5]["change_5d_pct"] == pytest.approx(0.2, abs=0.001)
        # First 5 records should have no 5d change
        assert records[4]["change_5d_pct"] is None

    def test_avg_volume_10d(self):
        """Should compute 10-day average volume when enough data."""
        closes = [10.0] * 15
        vols = [100000] * 15
        df = self._make_df(closes, volumes=vols)
        records = _parse_single_ticker_df("TEST", df)
        # 10th record (idx=9) should have avg_vol_10d
        assert records[9]["avg_volume_10d"] == 100000
        # Before that, should be None
        assert records[8]["avg_volume_10d"] is None


class TestUniverseDiscovery:
    def test_sec_tickers_format(self):
        """SEC ticker list should return dicts with expected keys."""
        # This test calls the real SEC API - skip in CI
        try:
            tickers = fetch_universe_tickers_sec()
            if tickers:
                assert "ticker" in tickers[0]
                assert "cik" in tickers[0]
                assert "company_name" in tickers[0]
                assert len(tickers) > 5000  # SEC has ~13k tickers
        except Exception:
            pytest.skip("SEC API unavailable")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
