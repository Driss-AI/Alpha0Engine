"""Tests for private company proxy screening."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from private_proxy import (
    estimate_total_raised, estimate_last_round_valuation,
    estimate_burn_rate, screen_private_company,
)


def test_total_raised_from_form_d():
    signals = [
        {"signal_type": "form_d", "raw_data": {"totalOfferingAmount": 50000000}},
        {"signal_type": "form_d", "raw_data": {"totalOfferingAmount": 75000000}},
    ]
    assert estimate_total_raised(signals) == 75000000


def test_no_form_d():
    assert estimate_total_raised([{"signal_type": "github_star"}]) is None


def test_valuation_estimate():
    signals = [
        {"signal_type": "form_d", "signal_date": "2025-01-01",
         "raw_data": {"totalOfferingAmount": 50000000}},
    ]
    val = estimate_last_round_valuation(signals)
    assert val == 200000000  # 50M * 4x


def test_burn_rate():
    signals = [
        {"signal_type": "form_d", "signal_date": "2025-01-01",
         "raw_data": {"totalOfferingAmount": 48000000}},
    ]
    burn = estimate_burn_rate(signals)
    assert burn == 2000000  # 48M / 24


def test_full_private_screen():
    signals = [
        {"signal_type": "form_d", "signal_date": "2025-01-01",
         "raw_data": {"totalOfferingAmount": 50000000}},
        {"signal_type": "secondary_trade", "signal_date": "2025-06-01",
         "value": 0.1, "raw_data": {}},
    ]
    result = screen_private_company(signals)
    assert result["total_raised"] == 50000000
    assert result["form_d_count"] == 1
    assert result["secondary_trade_count"] == 1
