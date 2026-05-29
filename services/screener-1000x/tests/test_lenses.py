"""
Tests — 1000x Screener Lenses & Composite Engine
===================================================
Unit tests for all five scoring lenses and the composite engine.
Uses reference patterns: SPRB (binary catalyst) and SNDK (earnings inflection).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lens_binary_catalyst import (
    score_binary_catalyst,
    _inverse_mcap_score,
    _catalyst_proximity_score,
    _cash_runway_factor,
    detect_catalysts_from_signals,
)
from lens_earnings_inflection import (
    _compute_trajectory,
    _score_eps_trajectory,
    _score_revenue_acceleration,
    _score_margin_expansion,
    _quarters_until_profit,
)
from lens_demand_rider import (
    _match_megatrend_keywords,
    _score_institutional_neglect,
    score_demand_rider,
)
from lens_float_mechanics import (
    _categorize_float,
    _score_float_size,
    _score_short_interest,
    _compute_squeeze_potential,
)
from lens_smart_money import (
    _score_institutional_buying,
    _score_insider_buying,
    score_smart_money,
)
from composite_engine import (
    compute_1000x_score,
    _count_active_lenses,
    _convergence_bonus,
)


# ═══════════════════════════════════════════════════════════
# LENS 1 — Binary Catalyst
# ═══════════════════════════════════════════════════════════
class TestBinaryCatalyst:
    def test_inverse_mcap_nano(self):
        """Nano-cap <$50M should score 1.0."""
        assert _inverse_mcap_score(30_000_000) == 1.0

    def test_inverse_mcap_micro(self):
        """Micro-cap $150-300M should score 0.75."""
        assert _inverse_mcap_score(200_000_000) == 0.75

    def test_inverse_mcap_large(self):
        """Large cap >$2B should score near 0."""
        assert _inverse_mcap_score(10_000_000_000) == 0.05

    def test_inverse_mcap_none(self):
        assert _inverse_mcap_score(None) == 0.0

    def test_catalyst_proximity_optimal(self):
        """30 days out = optimal window."""
        assert _catalyst_proximity_score(30) == 1.0

    def test_catalyst_proximity_too_far(self):
        """400 days = too far out."""
        assert _catalyst_proximity_score(400) == 0.05

    def test_catalyst_proximity_very_near(self):
        """5 days = partially priced in."""
        assert _catalyst_proximity_score(5) == 0.60

    def test_cash_runway_strong(self):
        """30 months runway = safe to reach catalyst."""
        assert _cash_runway_factor(30) == 1.0

    def test_cash_runway_critical(self):
        """3 months runway = may not survive."""
        assert _cash_runway_factor(3) == 0.1

    def test_detect_fda_catalyst(self):
        """Should detect FDA keywords in signal notes."""
        signals = [
            {
                "signal_type": "crossover_filing",
                "notes": "Company filed NDA with FDA for drug approval",
                "raw_data": {},
                "signal_date": "2026-03-01",
            }
        ]
        catalysts = detect_catalysts_from_signals(signals)
        assert len(catalysts) >= 1
        assert catalysts[0]["type"] == "fda_approval"

    def test_sprb_pattern_scores_high(self):
        """SPRB-like setup: micro-cap + FDA catalyst + long runway."""
        signals = [
            {
                "signal_type": "crossover_filing",
                "notes": "PDUFA date approaching for FDA approval",
                "raw_data": {},
                "signal_date": "2026-04-01",
            }
        ]
        result = score_binary_catalyst(
            market_cap=80_000_000,       # $80M micro-cap
            cash_runway_months=24,       # 2 years runway
            signals=signals,
        )
        assert result["catalyst_score"] > 0.5
        assert result["catalyst_type"] is not None

    def test_no_catalysts(self):
        """No catalyst signals = zero score."""
        result = score_binary_catalyst(
            market_cap=100_000_000,
            cash_runway_months=12,
            signals=[],
        )
        assert result["catalyst_score"] == 0.0


# ═══════════════════════════════════════════════════════════
# LENS 2 — Earnings Inflection
# ═══════════════════════════════════════════════════════════
class TestEarningsInflection:
    def test_trajectory_inflecting(self):
        """Negative → approaching zero → positive = inflecting."""
        vals = [-2.0, -1.5, -0.8, -0.3, 0.1]
        trajectory = _compute_trajectory(vals)
        assert trajectory in ("inflecting", "inflected_positive")

    def test_trajectory_accelerating(self):
        """All positive and increasing = accelerating."""
        vals = [0.5, 0.8, 1.2]
        trajectory = _compute_trajectory(vals)
        assert trajectory == "accelerating"

    def test_trajectory_declining(self):
        """All negative and getting worse = declining."""
        vals = [-0.5, -1.0, -2.0]
        trajectory = _compute_trajectory(vals)
        assert trajectory == "declining"

    def test_trajectory_insufficient(self):
        """Too few data points."""
        vals = [0.5]
        trajectory = _compute_trajectory(vals)
        assert trajectory == "insufficient_data"

    def test_eps_inflecting_scores_high(self):
        """Inflecting trajectory should score 1.0."""
        score = _score_eps_trajectory("inflecting", [-0.5, -0.2, 0.1])
        assert score == 1.0

    def test_revenue_acceleration_positive(self):
        """Accelerating revenue growth should score high."""
        rev = [100, 110, 125, 150]  # growth rate increasing
        score, accel = _score_revenue_acceleration(rev)
        assert score >= 0.4
        assert accel is not None

    def test_margin_expansion(self):
        """Expanding margins should score well."""
        gp = [30, 35, 42, 50]
        rev = [100, 105, 110, 115]
        score, rate = _score_margin_expansion(gp, rev)
        assert score >= 0.5
        assert rate > 0

    def test_quarters_to_profit_already(self):
        """Already profitable = 0 quarters."""
        assert _quarters_until_profit([0.5, 0.8, 1.0]) == 0

    def test_quarters_to_profit_approaching(self):
        """Improving losses: should estimate quarters."""
        result = _quarters_until_profit([-2.0, -1.5, -1.0, -0.5])
        assert result is not None
        assert result > 0


# ═══════════════════════════════════════════════════════════
# LENS 3 — Demand Rider
# ═══════════════════════════════════════════════════════════
class TestDemandRider:
    def test_megatrend_ai(self):
        """AI keywords should match ai_ml trend."""
        text = "Company develops large language models and AI accelerators"
        matches = _match_megatrend_keywords(text)
        assert "ai_ml" in matches
        assert matches["ai_ml"] > 0.3

    def test_megatrend_defense(self):
        """Defense keywords should match."""
        text = "Secured DOD contract for unmanned drone systems"
        matches = _match_megatrend_keywords(text)
        assert "defense_security" in matches

    def test_megatrend_no_match(self):
        """Generic text should not match."""
        text = "Company sells office supplies"
        matches = _match_megatrend_keywords(text)
        assert len(matches) == 0

    def test_institutional_neglect_nano(self):
        """Nano-cap with no 13F coverage = max neglect."""
        score = _score_institutional_neglect(50_000_000, 0, "public")
        assert score >= 0.9

    def test_institutional_neglect_large(self):
        """Large cap with many 13F holders = low neglect."""
        score = _score_institutional_neglect(10_000_000_000, 50, "public")
        assert score < 0.1

    def test_demand_rider_ai_micro(self):
        """Small AI company should score well."""
        signals = [
            {"signal_type": "patent_filing", "notes": "AI inference accelerator patent",
             "raw_data": {}, "signal_date": None},
        ]
        result = score_demand_rider(
            signals=signals,
            entity_type="public",
            sector="semiconductors",
            market_cap=200_000_000,
        )
        assert result["demand_score"] > 0.3
        assert result["megatrend_alignment"] is not None


# ═══════════════════════════════════════════════════════════
# LENS 4 — Float Mechanics
# ═══════════════════════════════════════════════════════════
class TestFloatMechanics:
    def test_categorize_nano_float(self):
        assert _categorize_float(3_000_000) == "nano"

    def test_categorize_micro_float(self):
        assert _categorize_float(10_000_000) == "micro"

    def test_categorize_large_float(self):
        assert _categorize_float(500_000_000) == "large"

    def test_float_score_nano(self):
        """Nano float should score near 1.0."""
        score = _score_float_size(1_500_000)
        assert score == 1.0

    def test_short_interest_extreme(self):
        """>40% short float should score 1.0."""
        score = _score_short_interest(0.45)
        assert score == 1.0

    def test_short_interest_low(self):
        """<5% short float should score low."""
        score = _score_short_interest(0.03)
        assert score == 0.10

    def test_squeeze_potential_triple(self):
        """All dimensions high = high squeeze."""
        squeeze = _compute_squeeze_potential(0.8, 0.9, 0.7)
        assert squeeze > 0.7

    def test_squeeze_potential_no_shorts(self):
        """No short interest = no squeeze."""
        squeeze = _compute_squeeze_potential(0.9, 0.0, 0.5)
        assert squeeze == 0.0


# ═══════════════════════════════════════════════════════════
# LENS 5 — Smart Money
# ═══════════════════════════════════════════════════════════
class TestSmartMoney:
    def test_institutional_buying_multiple(self):
        """Multiple 13F buyers in micro-cap = high score."""
        signals = [
            {"signal_type": "sec_13f", "signal_date": "2026-03-01",
             "raw_data": {"value_usd": 500_000}, "notes": None},
            {"signal_type": "sec_13f", "signal_date": "2026-04-01",
             "raw_data": {"value_usd": 300_000}, "notes": None},
            {"signal_type": "sec_13f", "signal_date": "2026-04-15",
             "raw_data": {"value_usd": 200_000}, "notes": None},
        ]
        result = _score_institutional_buying(signals, 100_000_000)
        assert result["score"] > 0.5
        assert result["buy_count"] == 3

    def test_institutional_buying_none(self):
        """No 13F data = zero."""
        result = _score_institutional_buying([], None)
        assert result["score"] == 0.0

    def test_insider_buying_cluster(self):
        """Multiple insiders buying = strong cluster signal."""
        signals = [
            {"signal_type": "form_4_insider", "signal_date": "2026-04-01",
             "raw_data": {"transaction_type": "Purchase", "value_usd": 50000,
                          "insider_name": "CEO John", "shares": 10000}, "notes": "buy"},
            {"signal_type": "form_4_insider", "signal_date": "2026-04-05",
             "raw_data": {"transaction_type": "Purchase", "value_usd": 30000,
                          "insider_name": "CFO Jane", "shares": 5000}, "notes": "buy"},
            {"signal_type": "form_4_insider", "signal_date": "2026-04-10",
             "raw_data": {"transaction_type": "Purchase", "value_usd": 25000,
                          "insider_name": "CTO Bob", "shares": 4000}, "notes": "buy"},
        ]
        result = _score_insider_buying(signals, 50_000_000)
        assert result["score"] > 0.6
        assert result["unique_insiders"] == 3

    def test_smart_money_convergence(self):
        """Both institutional + insider buying = convergence bonus."""
        signals = [
            {"signal_type": "sec_13f", "signal_date": "2026-03-01",
             "raw_data": {"value_usd": 500_000}, "notes": None},
            {"signal_type": "sec_13f", "signal_date": "2026-04-01",
             "raw_data": {"value_usd": 300_000}, "notes": None},
            {"signal_type": "sec_13f", "signal_date": "2026-04-10",
             "raw_data": {"value_usd": 200_000}, "notes": None},
            {"signal_type": "form_4_insider", "signal_date": "2026-04-01",
             "raw_data": {"transaction_type": "Purchase", "value_usd": 50000,
                          "insider_name": "CEO", "shares": 10000}, "notes": "buy"},
            {"signal_type": "form_4_insider", "signal_date": "2026-04-05",
             "raw_data": {"transaction_type": "Purchase", "value_usd": 30000,
                          "insider_name": "CFO", "shares": 5000}, "notes": "buy"},
        ]
        result = score_smart_money(signals, market_cap=80_000_000)
        assert result["smart_money_score"] > 0.4


# ═══════════════════════════════════════════════════════════
# COMPOSITE ENGINE
# ═══════════════════════════════════════════════════════════
class TestCompositeEngine:
    def test_all_zeros(self):
        """No lens firing = PASS."""
        result = compute_1000x_score()
        assert result["composite_score"] == 0.0
        assert result["conviction_tier"] == "PASS"
        assert result["active_lenses"] == 0

    def test_single_strong_lens(self):
        """Single strong lens = SPECULATIVE or WATCH."""
        result = compute_1000x_score(catalyst_score=0.9)
        assert result["conviction_tier"] in ("SPECULATIVE", "WATCH")
        assert result["active_lenses"] == 1
        assert result["top_lens"] == "Binary Catalyst"

    def test_sprb_pattern(self):
        """SPRB: strong catalyst + strong float = high tier."""
        result = compute_1000x_score(
            catalyst_score=0.85,
            float_score=0.80,
            smart_money_score=0.60,
        )
        assert result["conviction_tier"] in ("HIGH", "CONVICTION")
        assert result["active_lenses"] >= 3
        assert "SPRB-pattern" in result["screening_notes"]

    def test_sndk_pattern(self):
        """SNDK: earnings inflection + demand = high tier."""
        result = compute_1000x_score(
            earnings_score=0.80,
            demand_score=0.70,
            smart_money_score=0.50,
        )
        assert result["conviction_tier"] in ("HIGH", "WATCH")
        assert "SNDK-pattern" in result["screening_notes"]

    def test_all_lenses_firing(self):
        """All 5 lenses strong = CONVICTION with max bonuses."""
        result = compute_1000x_score(
            catalyst_score=0.80,
            earnings_score=0.75,
            demand_score=0.70,
            float_score=0.80,
            smart_money_score=0.75,
        )
        assert result["conviction_tier"] == "CONVICTION"
        assert result["active_lenses"] == 5
        assert result["bonuses"]["convergence"] > 0
        assert result["bonuses"]["synergy"] > 0

    def test_convergence_bonus_calculation(self):
        """Active lenses should increase convergence bonus."""
        scores_2 = {"a": 0.5, "b": 0.5, "c": 0.1, "d": 0.1, "e": 0.1}
        scores_4 = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5, "e": 0.1}
        assert _convergence_bonus(scores_4) > _convergence_bonus(scores_2)

    def test_count_active(self):
        scores = {
            "binary_catalyst": 0.5,
            "earnings_inflection": 0.1,
            "demand_rider": 0.4,
            "float_mechanics": 0.8,
            "smart_money": 0.0,
        }
        assert _count_active_lenses(scores) == 3  # 0.5, 0.4, 0.8 above 0.30


# ═══════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
