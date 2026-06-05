"""
L2 — Biotech Catalysts lane (Sprint 7.1)

Megatrend: FDA / clinical-milestone repricings. Small biotechs reprice violently
on binary regulatory and trial events.
Bottlenecks: the gating events themselves — PDUFA dates, AdCom decisions, trial
readouts — plus the AI-drug-discovery / genomics platform angle.

Example exposed companies: SPRB-pattern micro-caps, RXRX, VKTX, TGTX, VIR.
"""
from .base import Lane, UniverseFilter

L2_BIOTECH = Lane(
    lane_id="L2_BIOTECH",
    name="Biotech Catalysts",
    megatrend="FDA / clinical-milestone repricings",
    bottlenecks={
        "fda_decision": (
            "pdufa", "prescription drug user fee", "fda approval",
            "complete response letter", "crl", "bla", "nda",
            "accelerated approval", "breakthrough therapy", "fast track",
            "priority review",
        ),
        "advisory_committee": (
            "advisory committee", "adcom", "fda panel", "odac", "cardiovascular panel",
        ),
        "clinical_trial": (
            "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii",
            "topline data", "primary endpoint", "clinical trial", "readout",
            "interim analysis", "pivotal trial", "registrational",
        ),
        "ai_drug_discovery": (
            "ai drug discovery", "machine learning drug", "in silico",
            "generative chemistry", "ai-designed", "computational biology",
            "protein structure prediction",
        ),
        "genomics": (
            "gene therapy", "cell therapy", "crispr", "mrna", "genomics",
            "precision medicine", "car-t", "antibody drug conjugate",
            "bispecific", "radiopharmaceutical", "glp-1", "rna interference",
        ),
    },
    keywords=(
        "biotech", "clinical-stage", "pipeline", "indication", "oncology",
        "rare disease", "orphan drug", "licensing deal", "partnership",
    ),
    catalyst_types=(
        "pdufa_date",
        "adcom_date",
        "trial_readout",
        "phase_advance",
        "fda_approval",
        "crl",
        "licensing_deal",
    ),
    # Biotech is the classic binary-catalyst lane — a single PDUFA/readout drives
    # the move. Weight binary_catalyst heaviest; float mechanics still matter
    # (low-float biotech squeezes); demand_rider matters least.
    scoring_weights={
        "binary_catalyst": 0.40,
        "earnings_inflection": 0.05,
        "demand_rider": 0.10,
        "float_mechanics": 0.20,
        "smart_money": 0.25,
    },
    red_flags=(
        "trial_failure",
        "going_concern",
        "recent_dilutive_offering",
        "reverse_split",
        "single_asset_binary",
    ),
    universe_filters=UniverseFilter(
        market_cap_min_usd=15e6,
        market_cap_max_usd=500e6,     # the micro-cap wedge — SPRB lesson
        sectors=("biotech", "pharma", "healthcare", "life sciences"),
    ),
    # Backtest 2026-05-30: corr(composite, 90d return) = +0.07 — the linear
    # composite does NOT yet rank biotech (binary/outlier-driven returns).
    # Unvalidated → capped at DEEP_DIVE until event-conditioned scoring is
    # forward-tested on live matured alerts (Sprint 12).
    calibration_status="unvalidated",
)
