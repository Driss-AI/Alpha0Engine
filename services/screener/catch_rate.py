"""
Retrospective catch-rate harness — "would we have caught it?"
=============================================================
(RESTRUCTURE.md §3.4)

For each historical explosion case, reconstruct what was PUBLICLY KNOWABLE
N days before the move and push it through the engine's REAL scoring path:

    signals → lenses → lane-weighted composite → red flags → axes → bucket

A case is CAUGHT at a horizon when the bucket is DEEP_DIVE or better — i.e.
the engine would have told a human "research this now" before the move.

This is the anti-circular counterpart to scripts/seed_known_cases.py: that
script hand-assigns lens scores (so it can only validate the composite math);
this harness feeds raw signal-shaped inputs so every lens, red flag, axis and
bucket rule is exercised for real.

Case data honesty: the shipped cases are ARCHETYPE RECONSTRUCTIONS — the
shape of documented setups (SPRB-class PDUFA plays, low-float squeezes,
pump-shells) with representative numbers, NOT verified as-of-date market
data. Each case says so in `provenance`. Replace with verified numbers as
they are researched; the harness doesn't care where the facts come from.

The earnings lens (live XBRL fetch) is held at 0.0 — consistent with the
pre-revenue / early-stage names this pattern targets, where that lens is
inactive anyway.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from lens_binary_catalyst import score_binary_catalyst
from lens_demand_rider import score_demand_rider
from lens_float_mechanics import score_float_mechanics
from lens_smart_money import score_smart_money
from composite_engine import compute_1000x_score

from shared.lanes import get_lane
from shared.scoring import compute_axes, classify_bucket, detect_red_flags

CAUGHT_BUCKETS = ("DEEP_DIVE", "SETUP_READY")


# ── Case schema ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AsOf:
    """Facts publicly knowable `days_before` the move began."""
    days_before: int
    market_cap_usd: Optional[float]
    cash_runway_months: Optional[float]
    # Float mechanics (as a float_snapshot signal would carry them)
    float_shares: Optional[float] = None
    short_interest: Optional[float] = None
    short_pct_float: Optional[float] = None
    days_to_cover: Optional[float] = None
    # Dated catalyst visible at the as-of date
    catalyst_signal_type: Optional[str] = None   # "fda_catalyst" | "clinical_trial" | 8-K category
    catalyst_in_days: Optional[int] = None       # event date minus as-of date
    catalyst_phase: Optional[str] = None         # "PHASE3" etc. (trials)
    catalyst_notes: str = ""                     # keyword surface ("PDUFA date set...")
    # Smart money visible at the as-of date
    insider_buys_usd: tuple = ()                 # open-market buys (one signal each)
    institutional_holding_usd: Optional[float] = None
    # Price/volume state
    volume_ratio: Optional[float] = None
    # Red flags knowable at the as-of date (e.g. "going_concern")
    extra_red_flags: tuple = ()


@dataclass(frozen=True)
class Case:
    case_id: str
    ticker: str
    company: str
    lane_id: Optional[str]                       # lane whose weights apply (None = global)
    sector: Optional[str]
    description: str                             # business summary (feeds demand lens)
    outcome: str                                 # "winner" | "false_positive"
    move: str                                    # human note, e.g. "$8 → $200 over 3 weeks"
    provenance: str                              # where the numbers came from
    asof: tuple = field(default_factory=tuple)   # tuple[AsOf, ...]


# ── Signal reconstruction ───────────────────────────────────────────────────

def build_signals(a: AsOf, ticker: str) -> list[dict[str, Any]]:
    """Render an AsOf snapshot as the signal rows the ingesters would have
    written by that date. Shapes mirror services/sec + ingest-prices emitters."""
    now = datetime.utcnow()
    signals: list[dict[str, Any]] = []

    if a.catalyst_signal_type and a.catalyst_in_days is not None:
        raw: dict[str, Any] = {"catalyst_proximity_days": a.catalyst_in_days}
        if a.catalyst_phase:
            raw["phase"] = a.catalyst_phase
        signals.append({
            "signal_type": a.catalyst_signal_type,
            "signal_date": (now + timedelta(days=a.catalyst_in_days)).isoformat(),
            "value": 0.8,
            "raw_data": raw,
            "notes": a.catalyst_notes,
            "source": "catch_rate",
        })

    if a.float_shares or a.short_interest:
        signals.append({
            "signal_type": "float_snapshot",
            "signal_date": now.isoformat(),
            "value": 0.0,
            "raw_data": {
                "ticker": ticker,
                "float_shares": a.float_shares,
                "short_interest": a.short_interest,
                "short_pct_float": a.short_pct_float,
                "days_to_cover": a.days_to_cover,
            },
            "notes": "float snapshot",
            "source": "catch_rate",
        })

    for i, usd in enumerate(a.insider_buys_usd):
        signals.append({
            "signal_type": "insider_buy_cluster",
            "signal_date": (now - timedelta(days=5 + 3 * i)).isoformat(),
            "value": 0.8,
            "raw_data": {
                "transaction_type": "Purchase",
                "is_open_market_purchase": True,
                "value_usd": usd,
                "transaction_value": usd,
                "insider_name": f"insider-{i}",
            },
            "notes": "open-market insider buy",
            "source": "catch_rate",
        })

    if a.institutional_holding_usd:
        signals.append({
            "signal_type": "institutional_accumulation",
            "signal_date": (now - timedelta(days=20)).isoformat(),
            "value": 0.5,
            "raw_data": {"holding_value_usd": a.institutional_holding_usd,
                         "confirmation_only": True},
            "notes": "13F accumulation",
            "source": "catch_rate",
        })

    if a.volume_ratio:
        signals.append({
            "signal_type": "volume_awakening",
            "signal_date": now.isoformat(),
            "value": 0.6,
            "raw_data": {"volume_ratio": a.volume_ratio},
            "notes": "volume awakening",
            "source": "catch_rate",
        })

    return signals


# ── Scoring (the real path) ─────────────────────────────────────────────────

def score_asof(case: Case, a: AsOf) -> dict[str, Any]:
    """Run one as-of snapshot through lenses → composite → axes → bucket."""
    signals = build_signals(a, case.ticker)

    lens1 = score_binary_catalyst(
        market_cap=a.market_cap_usd,
        cash_runway_months=a.cash_runway_months,
        signals=signals,
    )
    lens3 = score_demand_rider(
        signals=signals,
        entity_type="public",
        sector=case.sector,
        market_cap=a.market_cap_usd,
        filing_text=case.description,
    )
    lens4 = asyncio.run(score_float_mechanics(
        ticker=None, cik=None, signals=signals,  # no network — snapshot only
    ))
    lens5 = score_smart_money(signals=signals, market_cap=a.market_cap_usd)

    weights = None
    lane_live_validated = True
    if case.lane_id:
        lane = get_lane(case.lane_id)
        weights = lane.scoring_weights
        lane_live_validated = lane.is_live_validated()

    composite = compute_1000x_score(
        catalyst_score=lens1["catalyst_score"],
        earnings_score=0.0,
        demand_score=lens3["demand_score"],
        float_score=lens4["float_score"],
        smart_money_score=lens5["smart_money_score"],
        weights=weights,
        lane_id=case.lane_id,
    )

    red = detect_red_flags(
        lane_id=case.lane_id,
        signals=signals,
        market_cap_usd=a.market_cap_usd,
        volume_ratio=a.volume_ratio,
        has_catalyst_date=a.catalyst_in_days is not None,
        extra_flags=list(a.extra_red_flags),
    )

    axes = compute_axes(
        composite_score=composite["composite_score"],
        active_lenses=composite["active_lenses"],
        market_cap_usd=a.market_cap_usd,
        cash_runway_months=a.cash_runway_months,
        short_pct_float=lens4.get("short_pct_float"),
        float_shares=lens4.get("float_shares"),
        days_to_cover=lens4.get("days_to_cover"),
        volume_ratio=a.volume_ratio,
        catalyst_proximity_days=lens1.get("catalyst_proximity_days"),
        evidence_count=len(signals),
        institutional_confirmation=a.institutional_holding_usd is not None,
        red_flag_count=len(red["red_flags"]),
        has_critical_flag=red["has_critical"],
    )
    bucket = classify_bucket(
        axes,
        has_critical_flag=red["has_critical"],
        has_dated_catalyst=a.catalyst_in_days is not None,
        lane_live_validated=lane_live_validated,
    )

    return {
        "days_before": a.days_before,
        "bucket": bucket,
        "caught": bucket in CAUGHT_BUCKETS,
        "composite_score": composite["composite_score"],
        "axes": axes.to_dict(),
        "red_flags": red["red_flags"],
        "lens_scores": {
            "catalyst": lens1["catalyst_score"],
            "demand": lens3["demand_score"],
            "float": lens4["float_score"],
            "smart_money": lens5["smart_money_score"],
        },
    }


def run_case(case: Case) -> dict[str, Any]:
    results = [score_asof(case, a) for a in case.asof]
    return {
        "case_id": case.case_id,
        "ticker": case.ticker,
        "outcome": case.outcome,
        "move": case.move,
        "results": results,
        # A winner counts as caught if ANY pre-move horizon flagged it.
        "caught_any": any(r["caught"] for r in results),
    }


def run_all(cases: Optional[list[Case]] = None) -> dict[str, Any]:
    from catch_rate_cases import CASES
    cases = cases if cases is not None else CASES
    rows = [run_case(c) for c in cases]
    winners = [r for r in rows if r["outcome"] == "winner"]
    fps = [r for r in rows if r["outcome"] == "false_positive"]
    return {
        "cases": rows,
        "n_winners": len(winners),
        "winners_caught": sum(1 for r in winners if r["caught_any"]),
        "n_false_positives": len(fps),
        # For a false positive, "caught" is BAD — we want the engine to skip it.
        "false_positives_flagged": sum(1 for r in fps if r["caught_any"]),
    }


def render_scoreboard(summary: dict[str, Any]) -> str:
    lines = [
        "CATCH-RATE SCOREBOARD — would the engine have flagged it before the move?",
        "=" * 74,
    ]
    for row in summary["cases"]:
        lines.append(f"\n{row['case_id']}  ({row['ticker']}, {row['outcome']}) — {row['move']}")
        for r in row["results"]:
            mark = "✓ CAUGHT " if r["caught"] else "  missed "
            if row["outcome"] == "false_positive":
                mark = "✗ FLAGGED" if r["caught"] else "✓ skipped"
            lens = r["lens_scores"]
            lines.append(
                f"  T-{r['days_before']:>3}d  {mark}  bucket={r['bucket']:<11}"
                f" composite={r['composite_score']:.3f}"
                f"  [cat {lens['catalyst']:.2f} | dem {lens['demand']:.2f}"
                f" | flt {lens['float']:.2f} | sm {lens['smart_money']:.2f}]"
            )
            if r["red_flags"]:
                lines.append(f"          red flags: {', '.join(r['red_flags'])}")
    lines.append("\n" + "=" * 74)
    lines.append(
        f"Winners caught:          {summary['winners_caught']}/{summary['n_winners']}"
    )
    lines.append(
        f"False positives flagged: {summary['false_positives_flagged']}"
        f"/{summary['n_false_positives']}  (lower is better)"
    )
    return "\n".join(lines)
