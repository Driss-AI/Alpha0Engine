"""
Red-flag detection (Sprint 7.6 → moved to shared in 9.3).

Lives in shared/ so both the risk-filter worker AND the screener (which builds
the bucket) can call it. risk-filter re-exports these for back-compat.

Shared flags apply to every candidate; lane-specific flags come from the lane
config. A flag in CRITICAL_RED_FLAGS forces bucket = NO TOUCH (9.5).
"""
from __future__ import annotations

from typing import Any, Optional

SHARED_RED_FLAGS = (
    "active_atm",                 # at-the-market offering — dilution into strength
    "recent_dilutive_offering",
    "going_concern",
    "no_volume",                  # can't enter/exit without getting trapped
    "no_catalyst_date",           # thesis with no dated catalyst
    "market_cap_under_15m",       # manipulation risk
    "insider_selling_cluster",
)

# Flags that are always critical (force NO TOUCH) wherever they appear.
CRITICAL_RED_FLAGS = frozenset({
    "going_concern",
    "active_atm",
    "recent_dilutive_offering",
    "reverse_split",
    "nasdaq_delisting_notice",
    "trial_failure",
    "gpu_contract_cancellation",
    "market_cap_under_15m",
})


def detect_red_flags(
    *,
    lane_id: Optional[str],
    signals: Optional[list[dict[str, Any]]] = None,
    market_cap_usd: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    has_catalyst_date: bool = True,
    extra_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Detect shared + lane-specific red flags for a candidate.

    Mechanical detectors evaluate from data on hand; data-dependent flags (ATM,
    going concern, reverse split, delisting) arrive via `extra_flags` from the
    callers that have them — e.g. the 8-K classifier's red_flag signals, surfaced
    here automatically (see signal scan below).

    Returns {red_flags, critical_flags, has_critical, lane_flag_vocabulary}.
    """
    signals = signals or []
    extra_flags = list(extra_flags or [])
    fired: set[str] = set()

    # Mechanical detectors.
    if market_cap_usd is not None and market_cap_usd < 15e6:
        fired.add("market_cap_under_15m")
    if volume_ratio is not None and volume_ratio < 0.2:
        fired.add("no_volume")
    if not has_catalyst_date:
        fired.add("no_catalyst_date")

    # Insider selling cluster (Form 4 risk signals).
    sell_signals = sum(
        1 for s in signals
        if s.get("signal_type") in ("insider_sell", "insider_sell_cluster")
    )
    if sell_signals >= 2:
        fired.add("insider_selling_cluster")

    # 8-K red_flag signals carry their flags in raw_data["red_flags"] (Sprint 8.3).
    for s in signals:
        if s.get("signal_type") == "red_flag":
            for f in (s.get("raw_data") or {}).get("red_flags", []):
                fired.add(f)

    # Caller-supplied flags.
    fired.update(extra_flags)

    # Lane vocabulary (shared + lane-specific) for transparency.
    vocab = set(SHARED_RED_FLAGS)
    if lane_id:
        try:
            from shared.lanes import get_lane
            vocab.update(get_lane(lane_id).red_flags)
        except Exception:
            pass

    critical = sorted(f for f in fired if f in CRITICAL_RED_FLAGS)
    return {
        "red_flags": sorted(fired),
        "critical_flags": critical,
        "has_critical": bool(critical),
        "lane_flag_vocabulary": sorted(vocab),
    }
