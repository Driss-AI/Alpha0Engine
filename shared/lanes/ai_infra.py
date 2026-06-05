"""
L1 — AI Infrastructure lane (Sprint 7.1)

Megatrend: the AI training + inference explosion.
Bottlenecks: the scarce physical/infrastructure layers that gate AI buildout —
power, data centers, optical interconnects, memory/HBM, GPU cloud, cooling,
grid equipment.

Example exposed companies: BE, VST, CEG, IREN, CORZ, APLD (power / data center),
LITE, COHR, AAOI, FN (optical), SNDK, MU, WDC, STX (memory/storage).
"""
from .base import Lane, UniverseFilter

L1_AI_INFRA = Lane(
    lane_id="L1_AI_INFRA",
    name="AI Infrastructure",
    megatrend="AI training + inference explosion",
    bottlenecks={
        "power": (
            "power purchase agreement", "ppa", "baseload power", "behind the meter",
            "data center power", "megawatt", "gigawatt", "grid interconnection",
            "fuel cell", "natural gas turbine", "nuclear power", "smr",
            "power generation", "energy supply",
        ),
        "data_center": (
            "data center", "datacenter", "hyperscale", "colocation", "colo",
            "rack density", "campus", "build-to-suit", "data center lease",
            "critical it load", "white space",
        ),
        "optical_networking": (
            "optical interconnect", "optical transceiver", "800g", "1.6t",
            "co-packaged optics", "silicon photonics", "dwdm", "optical module",
            "datacom", "pluggable optics",
        ),
        "memory_storage": (
            "high bandwidth memory", "hbm", "nand", "dram", "ssd",
            "enterprise ssd", "nearline", "storage capacity", "memory bandwidth",
            "ddr5", "nvme",
        ),
        "gpu_cloud": (
            "gpu cloud", "neocloud", "gpu hosting", "ai cloud", "h100", "h200",
            "blackwell", "gb200", "accelerated computing", "ai training cluster",
            "inference cluster", "gpu capacity",
        ),
        "cooling": (
            "liquid cooling", "direct-to-chip", "immersion cooling",
            "rear door heat exchanger", "cdu", "thermal management",
            "data center cooling",
        ),
        "grid_equipment": (
            "transformer", "switchgear", "substation", "transmission",
            "grid equipment", "electrical equipment", "power distribution",
            "high voltage",
        ),
    },
    keywords=(
        # thesis-level terms not tied to one bottleneck
        "artificial intelligence", "generative ai", "ai infrastructure",
        "hyperscaler", "nvidia", "capex", "backlog", "bookings",
    ),
    catalyst_types=(
        "hyperscaler_contract",
        "ppa_signed",
        "data_center_lease",
        "gpu_order",
        "utility_approval",
        "backlog_inflection",
        "nvda_partnership",
        "gov_contract",
    ),
    # AI-infra moves are driven by demand/backlog + smart-money confirmation more
    # than by single binary events; weight demand_rider + smart_money higher,
    # binary_catalyst lower than the biotech lane.
    scoring_weights={
        "binary_catalyst": 0.15,
        "earnings_inflection": 0.20,
        "demand_rider": 0.30,
        "float_mechanics": 0.10,
        "smart_money": 0.25,
    },
    red_flags=(
        "customer_concentration_over_50pct",
        "single_hyperscaler_dependency",
        "gpu_contract_cancellation",
        "power_interconnection_delay",
        "commodity_chip_margin_compression",
    ),
    universe_filters=UniverseFilter(
        market_cap_min_usd=15e6,      # exclude shells
        market_cap_max_usd=None,      # AI-infra winners can be large (CEG, VST) — no cap
        sectors=(
            "technology", "semiconductors", "energy", "utilities",
            "industrials", "infrastructure", "communication",
        ),
    ),
    # Backtest 2026-05-30: corr(composite, 90d return) = +0.55, winners/FPs
    # separate cleanly (winners +66% median vs FPs -22%). That backtest is
    # SUGGESTIVE but circular (seed_known_cases hand-assigns lens scores AND
    # labels winners), so it earns research_validated — NOT live_validated. Caps
    # at DEEP_DIVE until matured live alerts clear the bar (Sprint 12).
    calibration_status="research_validated",
)
