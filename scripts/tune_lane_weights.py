#!/usr/bin/env python3
"""
Lane weight tuner (Sprint 10.4)

Derives RECOMMENDED per-lane lens weights from backtest data: for each lane it
correlates each lens score with the realized 90-day forward return across the
validation rows, then normalizes the positive correlations into a weight vector.

It does NOT auto-edit shared/lanes/ — it prints a recommendation for human review,
because changing scoring weights is a calibration decision that should be
deliberate and logged in SPRINT_PLAN.md. Apply by editing the lane's
`scoring_weights` and re-running the backtest to confirm no regression.

Usage:
    python scripts/tune_lane_weights.py --lane L1_AI_INFRA
    python scripts/tune_lane_weights.py              # all lanes

Requires DATABASE_URL + a populated score_validations table.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

LENSES = ["catalyst_score", "earnings_score", "demand_score", "float_score", "smart_money_score"]
LENS_TO_WEIGHT_KEY = {
    "catalyst_score": "binary_catalyst",
    "earnings_score": "earnings_inflection",
    "demand_score": "demand_rider",
    "float_score": "float_mechanics",
    "smart_money_score": "smart_money",
}


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return round(num / (dx * dy), 4)


def recommend_weights(corrs: dict[str, float], floor: float = 0.05) -> dict[str, float]:
    """Turn lens→return correlations into a normalized weight vector.

    Negative/zero correlations get the floor (we don't drop a lens entirely —
    that's the human's call); positive correlations scale proportionally.
    """
    adj = {k: max(v, 0.0) for k, v in corrs.items()}
    total = sum(adj.values())
    if total <= 0:
        # No signal — equal weights.
        eq = round(1.0 / len(LENSES), 2)
        return {LENS_TO_WEIGHT_KEY[k]: eq for k in LENSES}
    raw = {LENS_TO_WEIGHT_KEY[k]: max(adj[k] / total, floor) for k in LENSES}
    # Renormalize after applying floor so they sum to 1.0.
    s = sum(raw.values())
    return {k: round(v / s, 3) for k, v in raw.items()}


async def tune(lane: str | None) -> str:
    from sqlalchemy import select
    from shared.clients.postgres import AsyncSessionLocal
    from shared.schemas.score_validation import ScoreValidation
    from shared.lanes import lane_ids, get_lane

    lanes = [lane] if lane else lane_ids()
    out = ["# Lane Weight Tuning Recommendation\n"]

    async with AsyncSessionLocal() as session:
        for lane_id in lanes:
            rows = (await session.execute(
                select(ScoreValidation).where(ScoreValidation.lane_id == lane_id)
            )).scalars().all()
            rows = [r for r in rows if r.return_90d is not None]
            out.append(f"\n## {lane_id} ({len(rows)} validation rows with 90d return)\n")
            if len(rows) < 5:
                out.append("_Insufficient data (<5 rows). Seed more cases / wait for live snapshots._\n")
                continue

            returns = [r.return_90d for r in rows]
            corrs = {}
            for lens in LENSES:
                xs = [getattr(r, lens) or 0.0 for r in rows]
                corrs[lens] = _pearson(xs, returns)

            out.append("| Lens | corr(lens, 90d return) |")
            out.append("|------|----------------------:|")
            for lens in LENSES:
                out.append(f"| {lens} | {corrs[lens]:+.3f} |")

            rec = recommend_weights(corrs)
            try:
                current = get_lane(lane_id).scoring_weights
            except Exception:
                current = {}
            out.append("\n| Weight | current | recommended |")
            out.append("|--------|--------:|------------:|")
            for k in rec:
                out.append(f"| {k} | {current.get(k, '—')} | {rec[k]} |")
            out.append("\n_Review, then edit the lane's `scoring_weights` if warranted "
                       "and log the change in SPRINT_PLAN.md._\n")

    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lane", default=None, help="L1_AI_INFRA / L2_BIOTECH")
    p.add_argument("--output", default=None, help="Write recommendation to file")
    args = p.parse_args()
    report = asyncio.run(tune(args.lane))
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Recommendation written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
