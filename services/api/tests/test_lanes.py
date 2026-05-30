"""Tests for the theme-lane architecture (Sprint 7).

Covers:
  7.1  shared/lanes config — registry, matching, universe filters, weight sums
  7.2  candidate_lanes table — CRUD + unique constraint
  7.5  catalyst types merged from lane configs
  7.6  lane-specific red flag vocabulary
"""
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.lanes import (
    ALL_LANES,
    L1_AI_INFRA,
    L2_BIOTECH,
    get_lane,
    lane_ids,
    match_lanes,
)
from shared.schemas.candidate_lane import CandidateLane


# ── 7.1 lane config ─────────────────────────────────────────────────────────

def test_two_active_lanes_registered():
    assert lane_ids() == ["L1_AI_INFRA", "L2_BIOTECH"]
    assert len(ALL_LANES) == 2


def test_every_lane_weights_sum_to_one():
    for lane in ALL_LANES:
        total = sum(lane.scoring_weights.values())
        assert 0.99 <= total <= 1.01, f"{lane.lane_id} weights sum {total}"


def test_lanes_have_required_fields():
    for lane in ALL_LANES:
        assert lane.lane_id and lane.name and lane.megatrend
        assert lane.bottlenecks, f"{lane.lane_id} has no bottlenecks"
        assert lane.catalyst_types, f"{lane.lane_id} has no catalyst types"
        assert lane.red_flags, f"{lane.lane_id} has no red flags"
        assert lane.all_keywords(), f"{lane.lane_id} has no keywords"


def test_get_lane_by_id():
    assert get_lane("L1_AI_INFRA") is L1_AI_INFRA
    assert get_lane("L2_BIOTECH") is L2_BIOTECH
    with pytest.raises(KeyError):
        get_lane("L99_NOPE")


def test_biotech_weights_favor_binary_catalyst():
    """Biotech is the binary-catalyst lane; AI-infra favors demand+smart money."""
    assert L2_BIOTECH.scoring_weights["binary_catalyst"] >= 0.35
    assert L1_AI_INFRA.scoring_weights["demand_rider"] >= 0.25
    assert L1_AI_INFRA.scoring_weights["binary_catalyst"] < L2_BIOTECH.scoring_weights["binary_catalyst"]


# ── 7.1 matching ──────────────────────────────────────────────────────────--

def test_match_ai_infra_power_company():
    matches = match_lanes(
        text="Bloom Energy fuel cell power purchase agreement for hyperscale "
             "data center, megawatt baseload power generation",
        sector="energy",
        market_cap_usd=5e9,
    )
    assert any(m.lane_id == "L1_AI_INFRA" for m in matches)
    l1 = next(m for m in matches if m.lane_id == "L1_AI_INFRA")
    assert "power" in l1.bottlenecks


def test_match_biotech_microcap():
    matches = match_lanes(
        text="clinical-stage biotech announces PDUFA date for lead oncology "
             "asset, phase 3 topline data primary endpoint met",
        sector="biotech",
        market_cap_usd=200e6,
    )
    assert any(m.lane_id == "L2_BIOTECH" for m in matches)
    l2 = next(m for m in matches if m.lane_id == "L2_BIOTECH")
    assert "fda_decision" in l2.bottlenecks or "clinical_trial" in l2.bottlenecks


def test_biotech_universe_filter_excludes_large_cap():
    """L2 caps at $500M — a $900M biotech must not match."""
    matches = match_lanes(
        text="phase 3 readout pdufa fda approval",
        sector="biotech",
        market_cap_usd=900e6,
    )
    assert not any(m.lane_id == "L2_BIOTECH" for m in matches)


def test_shell_excluded_by_min_market_cap():
    """Both lanes require >= $15M market cap."""
    matches = match_lanes(
        text="data center power phase 3 pdufa optical hbm",
        sector="technology",
        market_cap_usd=5e6,
    )
    assert matches == []


def test_company_can_match_multiple_bottlenecks():
    matches = match_lanes(
        text="data center liquid cooling 800G optical transceiver HBM memory "
             "gpu cloud hosting power purchase agreement transformer substation",
        sector="technology",
        market_cap_usd=2e9,
    )
    l1 = next(m for m in matches if m.lane_id == "L1_AI_INFRA")
    assert len(l1.bottlenecks) >= 3


def test_no_match_for_irrelevant_company():
    matches = match_lanes(
        text="regional restaurant chain quarterly same-store sales growth",
        sector="consumer",
        market_cap_usd=300e6,
    )
    assert matches == []


# ── 7.5 catalyst types ───────────────────────────────────────────────────---

def test_catalyst_types_include_lane_types():
    from shared.schemas.catalyst_event import CATALYST_TYPES
    # base types still present
    for base in ("earnings", "fda", "trial", "merger"):
        assert base in CATALYST_TYPES
    # lane-specific types merged in
    for ai in ("hyperscaler_contract", "ppa_signed", "data_center_lease", "gpu_order"):
        assert ai in CATALYST_TYPES
    for bio in ("pdufa_date", "adcom_date", "trial_readout", "phase_advance"):
        assert bio in CATALYST_TYPES


def test_catalyst_types_no_duplicates():
    from shared.schemas.catalyst_event import CATALYST_TYPES
    assert len(CATALYST_TYPES) == len(set(CATALYST_TYPES))


# ── 7.2 candidate_lanes table ────────────────────────────────────────────---

@pytest.mark.asyncio
async def test_candidate_lane_crud(session: AsyncSession):
    row = CandidateLane(
        entity_id="ent-be",
        ticker="BE",
        lane_id="L1_AI_INFRA",
        lane_score=0.42,
        bottleneck_exposure=["power", "data_center"],
    )
    session.add(row)
    await session.commit()

    from sqlmodel import select
    fetched = (await session.exec(
        select(CandidateLane).where(CandidateLane.entity_id == "ent-be")
    )).all()
    assert len(fetched) == 1
    assert fetched[0].lane_id == "L1_AI_INFRA"
    assert fetched[0].bottleneck_exposure == ["power", "data_center"]


@pytest.mark.asyncio
async def test_candidate_lane_one_entity_multiple_lanes(session: AsyncSession):
    session.add_all([
        CandidateLane(entity_id="ent-iren", ticker="IREN", lane_id="L1_AI_INFRA", lane_score=0.3),
        CandidateLane(entity_id="ent-iren", ticker="IREN", lane_id="L2_BIOTECH", lane_score=0.1),
    ])
    await session.commit()

    from sqlmodel import select
    rows = (await session.exec(
        select(CandidateLane).where(CandidateLane.entity_id == "ent-iren")
    )).all()
    assert {r.lane_id for r in rows} == {"L1_AI_INFRA", "L2_BIOTECH"}


# ── 7.6 lane red flags ───────────────────────────────────────────────────---

def test_lane_red_flag_vocabularies_distinct():
    assert "single_hyperscaler_dependency" in L1_AI_INFRA.red_flags
    assert "trial_failure" in L2_BIOTECH.red_flags
    # they should not share lane-specific flags
    assert set(L1_AI_INFRA.red_flags).isdisjoint(set(L2_BIOTECH.red_flags))


# ── 7.3 lane assignment (integration) ─────────────────────────────────────--

import importlib.util
import os
from dataclasses import dataclass


def _load_lane_assignment():
    """Load services/screener-1000x/lane_assignment.py by path (hyphenated dir)."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "screener-1000x", "lane_assignment.py"
    )
    spec = importlib.util.spec_from_file_location("lane_assignment", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class _FakeEntity:
    id: str
    name: str
    ticker: str = None
    sector: str = None
    description: str = None
    exchange: str = None


@pytest.mark.asyncio
async def test_assign_lanes_creates_rows(session: AsyncSession):
    la = _load_lane_assignment()
    entity = _FakeEntity(
        id="ent-lite", name="Lumentum", ticker="LITE", sector="technology",
        description="800G optical transceiver co-packaged optics for AI training cluster",
    )
    rows = await la.assign_lanes(session, entity, signals=[], market_cap_usd=4e9)
    await session.commit()

    assert any(r.lane_id == "L1_AI_INFRA" for r in rows)
    from sqlmodel import select
    persisted = (await session.exec(
        select(CandidateLane).where(CandidateLane.entity_id == "ent-lite")
    )).all()
    assert len(persisted) >= 1
    assert "optical_networking" in persisted[0].bottleneck_exposure


@pytest.mark.asyncio
async def test_assign_lanes_removes_stale_lane(session: AsyncSession):
    """Re-assigning when the company no longer matches drops the old row."""
    la = _load_lane_assignment()

    # Seed a stale row the entity won't re-match.
    session.add(CandidateLane(
        entity_id="ent-x", ticker="X", lane_id="L2_BIOTECH", lane_score=0.4,
        bottleneck_exposure=["clinical_trial"],
    ))
    await session.commit()

    entity = _FakeEntity(
        id="ent-x", name="DataCo", ticker="X", sector="technology",
        description="data center power purchase agreement megawatt hyperscale",
    )
    await la.assign_lanes(session, entity, signals=[], market_cap_usd=3e9)
    await session.commit()

    from sqlmodel import select
    rows = (await session.exec(
        select(CandidateLane).where(CandidateLane.entity_id == "ent-x")
    )).all()
    lane_set = {r.lane_id for r in rows}
    assert "L2_BIOTECH" not in lane_set       # stale biotech row removed
    assert "L1_AI_INFRA" in lane_set          # new AI-infra row added
