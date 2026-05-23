"""Tests for hype detection."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hype_detector import detect_hype_patterns, compute_hype_score, compute_substance_score


def test_empty_signals():
    result = detect_hype_patterns([])
    assert result["hype_score"] == 0.0
    assert result["substance_score"] == 0.0
    assert result["hype_flag"] is False


def test_pure_hype():
    signals = [{"signal_type": "news_mention", "signal_date": "2026-01-01"}] * 20
    result = detect_hype_patterns(signals)
    assert result["hype_score"] > 0.3
    assert result["substance_score"] == 0.0
    assert result["hype_gap"] > 0.3
    assert result["hype_flag"] is True


def test_pure_substance():
    signals = [
        {"signal_type": "patent_grant", "signal_date": "2026-01-01"},
        {"signal_type": "github_commit", "signal_date": "2026-01-01"},
        {"signal_type": "job_posting", "signal_date": "2026-01-01"},
        {"signal_type": "crossover_filing", "signal_date": "2026-01-01"},
    ] * 5
    result = detect_hype_patterns(signals)
    assert result["substance_score"] > 0.5
    assert result["hype_gap"] < 0
    assert result["hype_flag"] is False


def test_ghost_repo_detection():
    signals = [
        {"signal_type": "github_star", "signal_date": "2026-01-01"},
    ] * 15
    result = detect_hype_patterns(signals)
    assert result["hype_flag"] is True
    assert any("GHOST_REPO" in p for p in result["patterns"])


def test_fundraise_only():
    signals = [
        {"signal_type": "form_d", "signal_date": "2026-01-01", "raw_data": {}},
    ]
    result = detect_hype_patterns(signals)
    assert any("FUNDRAISE_ONLY" in p for p in result["patterns"])


def test_balanced_signals():
    signals = [
        {"signal_type": "news_mention", "signal_date": "2026-01-01"},
        {"signal_type": "patent_grant", "signal_date": "2026-01-01"},
        {"signal_type": "github_commit", "signal_date": "2026-01-01"},
        {"signal_type": "github_star", "signal_date": "2026-01-01"},
    ]
    result = detect_hype_patterns(signals)
    assert abs(result["hype_gap"]) <= 0.5
