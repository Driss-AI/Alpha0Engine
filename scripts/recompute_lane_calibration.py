#!/usr/bin/env python3
"""
Lane calibration recompute — Sprint 12.3.

Reads each lane's MATURED alerts (those with a realized 90d forward return) from
the `alerts` table, computes the live calibration stats, and reports whether the
lane clears the `live_validated` bar (shared/scoring/calibration.py thresholds).

This is a REPORT, not a mutation. Promotion is applied by a human editing the
lane config (`shared/lanes/*.py`) — setting `calibration_status="live_validated"`
and pasting in the justifying stats — and logging it in SPRINT_PLAN.md. Keeping
lanes code-as-config means every promotion is versioned and reviewable.

Usage:
    python scripts/recompute_lane_calibration.py
    python scripts/recompute_lane_calibration.py --lane L1_AI_INFRA

Exit codes:
    0  report produced (regardless of whether any lane is promotable)
    1  DB / runtime error
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.alert import Alert
from shared.lanes import ALL_LANES, get_lane
from shared.scoring.calibration import compute_lane_stats, evaluate_promotion
from shared.logging import setup_logging, get_logger

setup_logging("lane-calibration")
logger = get_logger("lane-calibration")


async def _matured_returns(session, lane_id: str) -> list[float]:
    """90d returns for a lane's alerts whose 90d horizon has elapsed."""
    rows = (await session.execute(
        select(Alert).where(
            Alert.lane_id == lane_id,
            Alert.forward_return_90d.isnot(None),  # type: ignore[union-attr]
        )
    )).scalars().all()
    return [r.forward_return_90d for r in rows if r.forward_return_90d is not None]


def _format_lane_report(lane_id: str, current_status: str, decision: dict) -> str:
    s = decision["stats"]
    lines = [
        f"── {lane_id} ─────────────────────────────",
        f"  current_status : {current_status}",
        f"  matured alerts : {s['sample_size']}",
        f"  win_rate_90d   : {s['live_win_rate_90d']}",
        f"  median_ret_90d : {s['median_forward_return_90d']}",
        f"  false_pos_rate : {s['false_positive_rate']}",
    ]
    if decision["clears_bar"]:
        lines.append(f"  ➜ CLEARS the live_validated bar — recommend promoting {lane_id}.")
        lines.append(f"    Paste into shared/lanes (and log in SPRINT_PLAN.md):")
        lines.append(f"      calibration_status=\"live_validated\",")
        lines.append(f"      sample_size={s['sample_size']},")
        lines.append(f"      live_win_rate_90d={s['live_win_rate_90d']},")
        lines.append(f"      false_positive_rate={s['false_positive_rate']},")
        lines.append(f"      median_forward_return_90d={s['median_forward_return_90d']},")
    else:
        lines.append(f"  ➜ holds at {current_status}. Not yet live_validated:")
        for reason in decision["reasons"]:
            lines.append(f"      · {reason}")
    return "\n".join(lines)


async def run_recompute(only_lane: str | None = None) -> int:
    lanes = [get_lane(only_lane)] if only_lane else list(ALL_LANES)

    print("\n" + "═" * 60)
    print("LANE CALIBRATION RECOMPUTE (live matured alerts)")
    print("═" * 60)

    promotable = 0
    async with AsyncSessionLocal() as session:
        for lane in lanes:
            returns = await _matured_returns(session, lane.lane_id)
            stats = compute_lane_stats(returns)
            decision = evaluate_promotion(stats, lane.calibration_status)
            print(_format_lane_report(lane.lane_id, lane.calibration_status, decision))
            if decision["clears_bar"] and lane.calibration_status != "live_validated":
                promotable += 1

    print("═" * 60)
    print(f"{promotable} lane(s) recommended for promotion to live_validated.")
    print("═" * 60)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lane", help="Only recompute this lane id (e.g. L1_AI_INFRA)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run_recompute(args.lane))
    except Exception as e:
        logger.error(f"lane calibration recompute failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
