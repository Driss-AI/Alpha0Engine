"""Tests for the Sprint 9 scoring stack: axes, buckets, thesis, evidence, alerts table."""
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.scoring import (
    compute_axes, classify_bucket, build_thesis, detect_red_flags,
    is_alertable, bucket_label,
)
from shared.schemas.evidence_item import EvidenceItem
from shared.schemas.alert import Alert


# ── 9.4 multi-axis scoring ──────────────────────────────────────────────────

def test_axes_in_range():
    ax = compute_axes(composite_score=0.7, active_lenses=3, market_cap_usd=200e6,
                      catalyst_proximity_days=30, evidence_count=4)
    for v in ax.to_dict().values():
        assert 0.0 <= v <= 100.0


def test_small_cap_higher_opportunity():
    big = compute_axes(composite_score=0.7, active_lenses=3, market_cap_usd=50e9)
    small = compute_axes(composite_score=0.7, active_lenses=3, market_cap_usd=80e6)
    assert small.opportunity > big.opportunity


def test_critical_flag_floors_risk_high():
    ax = compute_axes(composite_score=0.8, active_lenses=4, has_critical_flag=True, red_flag_count=2)
    assert ax.risk >= 85


def test_timing_closer_catalyst_higher():
    assert compute_axes(composite_score=0.5, active_lenses=2, catalyst_proximity_days=10).timing > \
           compute_axes(composite_score=0.5, active_lenses=2, catalyst_proximity_days=200).timing


def test_no_catalyst_low_timing():
    ax = compute_axes(composite_score=0.5, active_lenses=2, catalyst_proximity_days=None)
    assert ax.timing <= 30


# ── 9.5 bucket classifier ───────────────────────────────────────────────────

def test_critical_flag_forces_no_touch():
    ax = compute_axes(composite_score=0.9, active_lenses=5, market_cap_usd=200e6,
                      catalyst_proximity_days=10, has_critical_flag=True, red_flag_count=1)
    assert classify_bucket(ax, has_critical_flag=True, has_dated_catalyst=True) == "NO_TOUCH"


def test_setup_ready_requires_dated_catalyst():
    ax = compute_axes(composite_score=0.8, active_lenses=4, market_cap_usd=180e6,
                      catalyst_proximity_days=20, evidence_count=5,
                      institutional_confirmation=True, volume_ratio=2.4)
    # With dated catalyst -> SETUP_READY
    assert classify_bucket(ax, has_dated_catalyst=True) == "SETUP_READY"
    # Without -> cannot be SETUP_READY (downgrades to DEEP_DIVE or lower)
    assert classify_bucket(ax, has_dated_catalyst=False) != "SETUP_READY"


def test_low_opportunity_is_pass():
    ax = compute_axes(composite_score=0.1, active_lenses=1, market_cap_usd=5e9)
    assert classify_bucket(ax, has_dated_catalyst=False) == "PASS"


def test_alertable_only_deep_dive_and_setup():
    assert is_alertable("DEEP_DIVE")
    assert is_alertable("SETUP_READY")
    assert not is_alertable("WATCH")
    assert not is_alertable("NO_TOUCH")
    assert bucket_label("SETUP_READY") == "SETUP READY"


def test_setup_ready_requires_live_validated():
    """Sprint 12: only a live_validated lane can graduate to SETUP_READY."""
    ax = compute_axes(composite_score=0.8, active_lenses=4, market_cap_usd=180e6,
                      catalyst_proximity_days=20, evidence_count=5,
                      institutional_confirmation=True, volume_ratio=2.4)
    live = classify_bucket(ax, has_dated_catalyst=True, lane_live_validated=True)
    not_live = classify_bucket(ax, has_dated_catalyst=True, lane_live_validated=False)
    assert live == "SETUP_READY"
    assert not_live == "DEEP_DIVE"   # research_validated / unvalidated gated down


def test_lane_calibration_statuses():
    """Sprint 12: L1 research_validated (backtest-suggestive), L2 unvalidated.
    Neither is live_validated yet, so neither can emit SETUP_READY."""
    from shared.lanes import L1_AI_INFRA, L2_BIOTECH
    assert L1_AI_INFRA.calibration_status == "research_validated"
    assert L2_BIOTECH.calibration_status == "unvalidated"
    assert L1_AI_INFRA.is_live_validated() is False
    assert L2_BIOTECH.is_live_validated() is False


def test_invalid_calibration_status_rejected():
    """A mistyped status must fail loud at construction (it gates real alerts)."""
    import pytest
    from shared.lanes.base import Lane
    with pytest.raises(ValueError):
        Lane(lane_id="LX", name="x", megatrend="x", calibration_status="validated")


def test_calibration_stats_and_promotion():
    """Sprint 12.3: stats + promotion decision from matured-alert 90d returns."""
    from shared.scoring import compute_lane_stats, evaluate_promotion

    # 24 alerts: 18 winners (~+30%), 6 losers (3 materially wrong at -30%).
    returns = [0.30] * 18 + [-0.05] * 3 + [-0.30] * 3
    stats = compute_lane_stats(returns)
    assert stats["sample_size"] == 24
    assert stats["live_win_rate_90d"] == round(18 / 24, 4)
    assert stats["false_positive_rate"] == round(3 / 24, 4)   # only the -30% ones
    assert stats["median_forward_return_90d"] == 0.30

    decision = evaluate_promotion(stats, "research_validated")
    assert decision["clears_bar"] is True
    assert decision["recommended_status"] == "live_validated"
    assert decision["reasons"] == []


def test_calibration_promotion_holds_below_bar():
    """Too few alerts / weak returns must NOT promote — holds current status."""
    from shared.scoring import compute_lane_stats, evaluate_promotion

    # Only 5 alerts and weak — fails sample size AND median return.
    stats = compute_lane_stats([0.05, -0.10, 0.02, -0.30, 0.01])
    decision = evaluate_promotion(stats, "research_validated")
    assert decision["clears_bar"] is False
    assert decision["recommended_status"] == "research_validated"
    assert any("sample_size" in r for r in decision["reasons"])

    # Empty history → unvalidated stays unvalidated.
    empty = evaluate_promotion(compute_lane_stats([]), "unvalidated")
    assert empty["clears_bar"] is False
    assert empty["recommended_status"] == "unvalidated"


# ── 9.3 red flags ───────────────────────────────────────────────────────────

def test_red_flags_from_8k_signal():
    signals = [{"signal_type": "red_flag", "raw_data": {"red_flags": ["going_concern"]}}]
    r = detect_red_flags(lane_id="L2_BIOTECH", signals=signals)
    assert "going_concern" in r["red_flags"]
    assert r["has_critical"] is True


def test_no_catalyst_date_flag():
    r = detect_red_flags(lane_id="L1_AI_INFRA", has_catalyst_date=False)
    assert "no_catalyst_date" in r["red_flags"]


# ── 9.2 thesis ──────────────────────────────────────────────────────────────

def test_thesis_has_mandatory_fields():
    t = build_thesis(
        ticker="BE", company="Bloom Energy", lane_id="L1_AI_INFRA",
        bottlenecks=["power"], evidence=[{"summary": "PPA", "source_url": "http://x"}],
        nearest_catalyst={"catalyst_type": "ppa_signed", "expected_date": "2026-07-15"},
        volume_ratio=2.3,
    ).to_dict()
    assert t["megatrend"] and t["bottleneck"] == "power"
    assert "Bloom Energy" in t["exposure"]
    assert t["has_dated_catalyst"] is True
    assert "2026-07-15" in t["why_now"]


def test_thesis_no_catalyst_downgrades():
    t = build_thesis(
        ticker="XYZ", company="XYZ", lane_id="L2_BIOTECH",
        bottlenecks=["clinical_trial"], evidence=[], nearest_catalyst=None,
    ).to_dict()
    assert t["has_dated_catalyst"] is False
    assert "no dated catalyst" in t["why_now"].lower()


# ── 9.1 evidence_items + 9.6 alerts tables ──────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_item_crud(session: AsyncSession):
    session.add(EvidenceItem(
        entity_id="ent-be", ticker="BE", lane_id="L1_AI_INFRA",
        source="sec", source_url="https://sec.gov/x", summary="200MW PPA",
    ))
    await session.commit()
    from sqlmodel import select
    rows = (await session.exec(select(EvidenceItem).where(EvidenceItem.ticker == "BE"))).all()
    assert len(rows) == 1
    assert rows[0].source_url == "https://sec.gov/x"


@pytest.mark.asyncio
async def test_alert_crud(session: AsyncSession):
    session.add(Alert(ticker="BE", lane_id="L1_AI_INFRA", bucket="SETUP_READY",
                      composite_score=0.8, why_now="ppa dated", delivered=True))
    await session.commit()
    from sqlmodel import select
    rows = (await session.exec(select(Alert).where(Alert.ticker == "BE"))).all()
    assert len(rows) == 1
    assert rows[0].bucket == "SETUP_READY"
    assert rows[0].delivered is True
