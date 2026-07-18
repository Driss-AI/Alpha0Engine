"""
Catch-rate cases — archetype reconstructions of documented setups.

⚠ Provenance: every case below is an ARCHETYPE — the documented *shape* of a
known setup class with representative numbers, not verified as-of-date market
data for the named inspiration. The harness is data-agnostic: as real as-of
reconstructions are researched (price/float/short/PDUFA-date history), replace
these with verified numbers and tighten the assertions in
tests/test_catch_rate.py. What matters here is that the engine's REAL scoring
path is exercised end-to-end against setups it must catch and traps it must
skip.

Winners = the engine should reach DEEP_DIVE+ before the move.
False positives = the engine should NOT (PASS / WATCH / NO_TOUCH).
"""
from catch_rate import AsOf, Case

CASES = [

    # ── Winners ─────────────────────────────────────────────────────────────

    Case(
        case_id="SERB_CLASS_PDUFA",
        ticker="SERB",
        company="SERB-class micro-cap biotech",
        lane_id="L2_BIOTECH",
        sector="Healthcare",
        description=(
            "Clinical-stage biopharmaceutical company developing a novel "
            "therapy; NDA under FDA priority review with a PDUFA target "
            "action date announced. Phase 3 pivotal trial met its primary "
            "endpoint."
        ),
        outcome="winner",
        move="~$8 → $200-class re-rating on FDA approval",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=90, market_cap_usd=60e6, cash_runway_months=14,
                 float_shares=4_000_000, short_interest=1_000_000,
                 short_pct_float=0.25, days_to_cover=9.0,
                 catalyst_signal_type="fda_catalyst", catalyst_in_days=90,
                 catalyst_notes="FDA PDUFA target action date set (NDA priority review)",
                 insider_buys_usd=(120_000,)),
            AsOf(days_before=60, market_cap_usd=70e6, cash_runway_months=13,
                 float_shares=4_000_000, short_interest=1_100_000,
                 short_pct_float=0.27, days_to_cover=9.5,
                 catalyst_signal_type="fda_catalyst", catalyst_in_days=60,
                 catalyst_notes="FDA PDUFA target action date set (NDA priority review)",
                 insider_buys_usd=(120_000, 60_000),
                 institutional_holding_usd=900_000),
            AsOf(days_before=30, market_cap_usd=85e6, cash_runway_months=12,
                 float_shares=4_000_000, short_interest=1_200_000,
                 short_pct_float=0.30, days_to_cover=10.0,
                 catalyst_signal_type="fda_catalyst", catalyst_in_days=30,
                 catalyst_notes="FDA PDUFA target action date set (NDA priority review)",
                 insider_buys_usd=(120_000, 60_000),
                 institutional_holding_usd=1_200_000,
                 volume_ratio=2.5),
        ),
    ),

    Case(
        case_id="PHASE3_READOUT",
        ticker="PH3X",
        company="Phase-3 readout micro-cap",
        lane_id="L2_BIOTECH",
        sector="Healthcare",
        description=(
            "Biotechnology company; pivotal Phase 3 trial fully enrolled with "
            "topline data expected next quarter. Cash into next year."
        ),
        outcome="winner",
        move="binary trial readout re-rating",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=60, market_cap_usd=120e6, cash_runway_months=16,
                 float_shares=9_000_000, short_interest=1_400_000,
                 short_pct_float=0.16, days_to_cover=6.0,
                 catalyst_signal_type="clinical_trial", catalyst_in_days=60,
                 catalyst_phase="PHASE3",
                 catalyst_notes="pivotal phase 3 topline data expected",
                 institutional_holding_usd=800_000),
            AsOf(days_before=30, market_cap_usd=130e6, cash_runway_months=15,
                 float_shares=9_000_000, short_interest=1_600_000,
                 short_pct_float=0.18, days_to_cover=6.5,
                 catalyst_signal_type="clinical_trial", catalyst_in_days=30,
                 catalyst_phase="PHASE3",
                 catalyst_notes="pivotal phase 3 topline data expected",
                 insider_buys_usd=(80_000,),
                 institutional_holding_usd=1_000_000,
                 volume_ratio=2.0),
        ),
    ),

    Case(
        case_id="AI_INFRA_SQUEEZE",
        ticker="PWRX",
        company="AI-infrastructure power micro-cap",
        lane_id="L1_AI_INFRA",
        sector="Industrials",
        description=(
            "Independent power producer expanding behind-the-meter capacity "
            "for data centers; signed a power purchase agreement with a "
            "hyperscaler for AI data center campus load; gpu cloud demand."
        ),
        outcome="winner",
        move="low-float squeeze on hyperscaler PPA",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=60, market_cap_usd=180e6, cash_runway_months=20,
                 float_shares=7_000_000, short_interest=1_300_000,
                 short_pct_float=0.19, days_to_cover=7.5,
                 catalyst_signal_type="hyperscaler_contract", catalyst_in_days=45,
                 catalyst_notes="power purchase agreement with hyperscaler; "
                                "contract award phase-in date announced",
                 insider_buys_usd=(250_000, 90_000),
                 institutional_holding_usd=1_500_000),
            AsOf(days_before=30, market_cap_usd=210e6, cash_runway_months=20,
                 float_shares=7_000_000, short_interest=1_500_000,
                 short_pct_float=0.21, days_to_cover=8.0,
                 catalyst_signal_type="hyperscaler_contract", catalyst_in_days=20,
                 catalyst_notes="power purchase agreement with hyperscaler; "
                                "contract award phase-in date announced",
                 insider_buys_usd=(250_000, 90_000),
                 institutional_holding_usd=2_000_000,
                 volume_ratio=3.0),
        ),
    ),

    # ── False positives (the traps) ─────────────────────────────────────────

    Case(
        case_id="NEG_PUMP_SHELL",
        ticker="PUMP",
        company="Sub-$15M promoted shell",
        lane_id="L2_BIOTECH",
        sector="Healthcare",
        description="Development-stage company; heavy promotion, no pipeline.",
        outcome="false_positive",
        move="promoted spike then -95%",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=30, market_cap_usd=9e6, cash_runway_months=3,
                 float_shares=2_000_000,
                 volume_ratio=6.0),
        ),
    ),

    Case(
        case_id="NEG_NO_CATALYST",
        ticker="DRFT",
        company="Driftwood no-catalyst micro-cap",
        lane_id=None,
        sector="Technology",
        description="Legacy IT services provider; flat revenue, no catalysts.",
        outcome="false_positive",
        move="drifted sideways then faded",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=30, market_cap_usd=300e6, cash_runway_months=30,
                 float_shares=60_000_000, short_interest=1_000_000,
                 short_pct_float=0.02, days_to_cover=1.0),
        ),
    ),

    Case(
        case_id="NEG_GOING_CONCERN",
        ticker="GCRN",
        company="Going-concern biotech with a dated catalyst",
        lane_id="L2_BIOTECH",
        sector="Healthcare",
        description=(
            "Clinical-stage biotech with Phase 3 readout scheduled — and a "
            "going-concern qualification plus an active at-the-market offering."
        ),
        outcome="false_positive",
        move="diluted into the catalyst; -80%",
        provenance="archetype reconstruction (replace with verified as-of data)",
        asof=(
            AsOf(days_before=30, market_cap_usd=45e6, cash_runway_months=2,
                 float_shares=5_000_000, short_interest=1_500_000,
                 short_pct_float=0.30, days_to_cover=9.0,
                 catalyst_signal_type="clinical_trial", catalyst_in_days=30,
                 catalyst_phase="PHASE3",
                 catalyst_notes="phase 3 topline expected",
                 extra_red_flags=("going_concern", "active_atm")),
        ),
    ),
]
