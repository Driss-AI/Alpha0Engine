"""
Lane calibration state machine (Sprint 12) — pure, testable.

Decides when a lane has earned `live_validated` — the only status that unlocks
SETUP_READY (see shared/scoring/buckets.py). A lane is promoted ONLY when its
matured-alert outcomes clear every threshold below.

Why a state machine instead of the old `calibrated: bool`:
  - The S10 backtest (corr +0.55 for L1) is SUGGESTIVE but circular —
    `scripts/seed_known_cases.py` hand-assigns the lens scores AND labels the
    winners, so a high correlation isn't proof the *live* engine ranks the same.
    That earns `research_validated`, which still caps at DEEP_DIVE.
  - Only real, matured alerts (the engine's own live calls, scored against
    realized forward returns) can promote a lane to `live_validated`.

`scripts/recompute_lane_calibration.py` computes these stats from the `alerts`
table and reports a recommendation. Promotion is applied by a human editing the
lane config (code-as-config) and recording the justifying stats — it is never
auto-mutated, to keep the lane definitions versioned and auditable.
"""
from __future__ import annotations

from statistics import median
from typing import Optional

# ── Promotion thresholds (live_validated). Documented + auditable. ──────────
MIN_MATURED_ALERTS = 20          # enough 90d outcomes to be non-anecdotal
MIN_WIN_RATE_90D = 0.50          # a majority of alerts up at 90d
MIN_MEDIAN_RETURN_90D = 0.10     # median alert at least +10% at 90d
MAX_FALSE_POSITIVE_RATE = 0.40   # at most 40% materially-wrong calls

# What counts as a win / a false positive, per alert (by 90d forward return).
WIN_THRESHOLD = 0.0              # > 0 at 90d = win
FALSE_POSITIVE_THRESHOLD = -0.20  # <= -20% at 90d = materially wrong (false positive)


def compute_lane_stats(returns_90d: list[float]) -> dict[str, Optional[float]]:
    """Summarize a lane's matured-alert 90d returns.

    `returns_90d` is the list of realized 90d returns (fractions, 0.25 = +25%)
    for that lane's alerts whose 90d horizon has elapsed.
    """
    n = len(returns_90d)
    if n == 0:
        return {
            "sample_size": 0,
            "live_win_rate_90d": None,
            "false_positive_rate": None,
            "median_forward_return_90d": None,
        }
    wins = sum(1 for r in returns_90d if r > WIN_THRESHOLD)
    fps = sum(1 for r in returns_90d if r <= FALSE_POSITIVE_THRESHOLD)
    return {
        "sample_size": n,
        "live_win_rate_90d": round(wins / n, 4),
        "false_positive_rate": round(fps / n, 4),
        "median_forward_return_90d": round(median(returns_90d), 4),
    }


def evaluate_promotion(stats: dict, current_status: str) -> dict:
    """Decide whether a lane clears the `live_validated` bar.

    Returns the decision plus the per-threshold reasons it failed (empty when it
    clears). Only ever recommends promotion to `live_validated`; it never
    downgrades — a lane that no longer clears the bar keeps its current status
    (a human reviews regressions).
    """
    n = stats.get("sample_size") or 0
    win = stats.get("live_win_rate_90d")
    fp = stats.get("false_positive_rate")
    med = stats.get("median_forward_return_90d")

    failed: list[str] = []
    if n < MIN_MATURED_ALERTS:
        failed.append(f"sample_size {n} < {MIN_MATURED_ALERTS}")
    if win is None or win < MIN_WIN_RATE_90D:
        failed.append(f"win_rate {win} < {MIN_WIN_RATE_90D}")
    if med is None or med < MIN_MEDIAN_RETURN_90D:
        failed.append(f"median_return {med} < {MIN_MEDIAN_RETURN_90D}")
    if fp is None or fp > MAX_FALSE_POSITIVE_RATE:
        failed.append(f"false_positive_rate {fp} > {MAX_FALSE_POSITIVE_RATE}")

    clears = not failed
    return {
        "clears_bar": clears,
        "recommended_status": "live_validated" if clears else current_status,
        "current_status": current_status,
        "reasons": failed,
        "stats": stats,
    }
