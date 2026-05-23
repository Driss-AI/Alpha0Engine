"""Tests for illiquidity risk scoring."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from illiquidity_scorer import compute_illiquidity_risk, score_runway_risk, score_signal_concentration


def test_critical_runway():
    assert score_runway_risk(2) == 1.0
    assert score_runway_risk(5) == 0.85
    assert score_runway_risk(30) == 0.05


def test_unknown_runway():
    assert score_runway_risk(None) == 0.5


def test_single_source_risk():
    signals = [{"signal_type": "form_d", "source": "edgar"}] * 10
    assert score_signal_concentration(signals) == 0.9


def test_diversified_sources():
    signals = [
        {"signal_type": "form_d", "source": "edgar"},
        {"signal_type": "patent_grant", "source": "uspto"},
        {"signal_type": "github_commit", "source": "github"},
        {"signal_type": "news_mention", "source": "newsapi"},
    ]
    assert score_signal_concentration(signals) < 0.5


def test_full_illiquidity_assessment():
    signals = [
        {"signal_type": "form_d", "signal_date": "2024-01-01", "source": "edgar",
         "raw_data": {"totalOfferingAmount": 50000000}},
        {"signal_type": "secondary_trade", "signal_date": "2026-01-01", "source": "forge", "value": -0.2},
    ]
    result = compute_illiquidity_risk(signals, estimated_runway=8)
    assert result["illiquidity_score"] > 0.3
    assert result["runway_risk"] > 0.5


def test_safe_company():
    signals = [
        {"signal_type": "form_d", "signal_date": "2026-04-01", "source": "edgar",
         "raw_data": {"totalOfferingAmount": 100000000}},
        {"signal_type": "patent_grant", "source": "uspto"},
        {"signal_type": "github_commit", "source": "github"},
        {"signal_type": "crossover_filing", "source": "sec_13f"},
    ]
    result = compute_illiquidity_risk(signals, estimated_runway=30)
    assert result["illiquidity_score"] < 0.4
    assert result["illiquidity_flag"] is False
