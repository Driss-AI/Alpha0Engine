"""
Catch-rate regression tests — the engine must catch the archetype setups it
exists to catch, and skip the traps, at every as-of horizon.

If a lens or bucket change breaks these, the engine has regressed on its core
job. Cases are archetype reconstructions (see catch_rate_cases.py provenance);
tighten as verified as-of data replaces them.
"""
from catch_rate import run_case, score_asof
from catch_rate_cases import CASES

CASES_BY_ID = {c.case_id: c for c in CASES}


def test_serb_class_pdufa_caught_at_every_horizon():
    """The SERB-class PDUFA setup — the product's reason to exist — must be
    DEEP_DIVE+ at 90, 60, and 30 days out."""
    case = CASES_BY_ID["SERB_CLASS_PDUFA"]
    for asof in case.asof:
        r = score_asof(case, asof)
        assert r["caught"], (
            f"missed SERB-class setup at T-{asof.days_before}d: "
            f"bucket={r['bucket']} composite={r['composite_score']}"
        )


def test_phase3_readout_caught():
    case = CASES_BY_ID["PHASE3_READOUT"]
    assert run_case(case)["caught_any"]


def test_ai_infra_squeeze_caught():
    """8-K category catalysts (hyperscaler_contract etc.) must be visible to
    the binary-catalyst lens — regression for the catalyst_map gap."""
    case = CASES_BY_ID["AI_INFRA_SQUEEZE"]
    result = run_case(case)
    assert result["caught_any"]
    for r in result["results"]:
        assert r["lens_scores"]["catalyst"] > 0, (
            "8-K category catalyst invisible to Lens 1 again"
        )


def test_pump_shell_not_flagged():
    """Sub-$15M promoted shell with no catalyst must be NO_TOUCH."""
    case = CASES_BY_ID["NEG_PUMP_SHELL"]
    r = score_asof(case, case.asof[0])
    assert r["bucket"] == "NO_TOUCH"


def test_no_catalyst_drift_not_flagged():
    case = CASES_BY_ID["NEG_NO_CATALYST"]
    r = score_asof(case, case.asof[0])
    assert not r["caught"]


def test_going_concern_blocks_even_dated_catalyst():
    """A dated catalyst must NOT override a going-concern + ATM combination."""
    case = CASES_BY_ID["NEG_GOING_CONCERN"]
    r = score_asof(case, case.asof[0])
    assert r["bucket"] == "NO_TOUCH"
    assert "going_concern" in r["red_flags"]


def test_winners_never_reach_setup_ready_while_lanes_unvalidated():
    """SETUP_READY stays locked behind live_validated lanes (Sprint 12 gate) —
    the catch-rate suite must not accidentally prove otherwise."""
    from shared.lanes import get_lane
    for case in CASES:
        if case.outcome != "winner" or not case.lane_id:
            continue
        if get_lane(case.lane_id).is_live_validated():
            continue
        for asof in case.asof:
            assert score_asof(case, asof)["bucket"] != "SETUP_READY"
