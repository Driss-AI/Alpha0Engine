"""Tests for moat scoring engine."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from moat_scorer import (
    compute_moat_score, score_patent_strength,
    score_github_momentum, score_talent_density,
)


def test_empty_signals():
    result = compute_moat_score([], sector_avg_signals=10)
    # competitive_position defaults to ~0.12 with 0 signals vs avg of 10
    # so composite won't be exactly 0, but patent/github/talent should be
    assert result["moat_score"] < 0.1
    assert result["patent_strength"] == 0.0
    assert result["github_momentum"] == 0.0
    assert result["talent_density"] == 0.0


def test_patent_signals():
    signals = [
        {"signal_type": "patent_filing", "signal_date": "2025-01-01", "raw_data": {}},
        {"signal_type": "patent_grant", "signal_date": "2025-06-01", "raw_data": {}},
        {"signal_type": "patent_grant", "signal_date": "2025-09-01", "raw_data": {}},
    ]
    score = score_patent_strength(signals)
    assert 0.0 < score <= 1.0


def test_github_momentum():
    signals = [
        {"signal_type": "github_star", "signal_date": "2025-01-01"},
        {"signal_type": "github_commit", "signal_date": "2025-01-01"},
    ] * 50
    score = score_github_momentum(signals)
    assert 0.0 < score <= 1.0


def test_talent_density_key_hires():
    signals = [
        {"signal_type": "job_posting", "notes": "CFO with IPO experience", "raw_data": {"title": "CFO"}},
        {"signal_type": "job_posting", "notes": "Senior Engineer", "raw_data": {"title": "Senior Engineer"}},
    ]
    score = score_talent_density(signals)
    assert score > 0.0


def test_composite_moat():
    signals = [
        {"signal_type": "patent_filing", "signal_date": "2025-01-01", "raw_data": {"cpc_classes": ["G06N", "H04L"]}},
        {"signal_type": "patent_grant", "signal_date": "2025-06-01", "raw_data": {"cpc_classes": ["G06F"]}},
        {"signal_type": "github_star", "signal_date": "2025-01-01"},
        {"signal_type": "github_commit", "signal_date": "2025-01-01"},
        {"signal_type": "job_posting", "notes": "VP Engineering", "raw_data": {"title": "VP Eng"}},
    ] * 10
    result = compute_moat_score(signals, sector_avg_signals=10)
    assert 0.0 < result["moat_score"] <= 1.0
    assert result["patent_strength"] > 0
    assert result["github_momentum"] > 0
