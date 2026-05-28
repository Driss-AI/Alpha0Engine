#!/usr/bin/env python3
"""
Calibration Report — CONVICTION vs WATCH Performance
=====================================================
Focused analysis: does the scoring engine actually separate winners
from losers? Outputs a concise calibration report with statistical tests.

Usage:
    python scripts/calibration_report.py
    python scripts/calibration_report.py --horizon 90 --output calibration.md
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date
from math import sqrt, erf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.score_validation import ScoreValidation
from shared.logging import setup_logging, get_logger

setup_logging("calibration-report")
logger = get_logger("calibration-report")

TIERS = ["CONVICTION", "HIGH", "WATCH", "SPECULATIVE", "PASS"]


def _mean(v): return sum(v) / len(v) if v else 0.0
def _std(v):
    if len(v) < 2: return 0.0
    m = _mean(v)
    return sqrt(sum((x - m)**2 for x in v) / (len(v) - 1))
def _median(v):
    s = sorted(v)
    n = len(s)
    return (s[n//2-1] + s[n//2]) / 2 if n % 2 == 0 else s[n//2] if n else 0.0


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    ma, mb = _mean(a), _mean(b)
    sa, sb = _std(a), _std(b)
    se = sqrt(sa**2/len(a) + sb**2/len(b)) if (sa > 0 or sb > 0) else 1e-10
    t = (ma - mb) / se if se > 0 else 0.0
    p = 1.0 - erf(abs(t) / sqrt(2))
    return round(t, 3), round(p, 4)


async def calibration(horizon: int) -> str:
    field = f"return_{horizon}d"
    outcome_field = f"outcome_{horizon}d"

    async with AsyncSessionLocal() as session:
        rows = (await session.exec(select(ScoreValidation))).all()

    if not rows:
        return "No data. Run backtest_dataset.py first."

    by_tier = defaultdict(list)
    for r in rows:
        ret = getattr(r, field)
        if ret is not None:
            by_tier[r.conviction_tier].append(r)

    lines = [
        f"# Calibration Report — {horizon}-Day Horizon",
        f"\nDate: {date.today()}",
        f"Records with {horizon}d returns: {sum(len(v) for v in by_tier.values())}",
    ]

    # Per-tier stats
    lines.append(f"\n## Tier Performance at {horizon} Days\n")
    lines.append("| Tier | N | Mean Return | Median | Std | Win% | Sharpe† |")
    lines.append("|------|--:|-----------:|-------:|----:|-----:|--------:|")

    tier_rets = {}
    for tier in TIERS:
        entries = by_tier.get(tier, [])
        rets = [getattr(r, field) for r in entries]
        tier_rets[tier] = rets

        if len(rets) < 3:
            lines.append(f"| {tier} | {len(rets)} | — | — | — | — | — |")
            continue

        m = _mean(rets)
        med = _median(rets)
        s = _std(rets)
        wr = sum(1 for r in rets if r >= 0.10) / len(rets)
        sharpe = m / s if s > 0 else 0.0

        lines.append(
            f"| {tier} | {len(rets)} | {m:+.2%} | {med:+.2%} | {s:.2%} "
            f"| {wr:.0%} | {sharpe:.2f} |"
        )

    lines.append("\n† Sharpe = mean / std (not annualized, no risk-free rate)\n")

    # Pairwise tests
    lines.append("## Statistical Tests\n")
    pairs = [("CONVICTION", "WATCH"), ("CONVICTION", "PASS"), ("HIGH", "SPECULATIVE")]
    for a_name, b_name in pairs:
        a = tier_rets.get(a_name, [])
        b = tier_rets.get(b_name, [])
        if len(a) < 3 or len(b) < 3:
            lines.append(f"- **{a_name} vs {b_name}:** insufficient data")
            continue
        t_stat, p_val = welch_t(a, b)
        diff = _mean(a) - _mean(b)
        sig = "SIGNIFICANT (p<0.05)" if p_val < 0.05 else "not significant"
        lines.append(
            f"- **{a_name} vs {b_name}:** diff={diff:+.2%}, "
            f"t={t_stat}, p={p_val} — {sig}"
        )

    # Monotonicity check
    lines.append("\n## Monotonicity Check\n")
    means = []
    for tier in TIERS:
        rets = tier_rets.get(tier, [])
        if len(rets) >= 3:
            means.append((tier, _mean(rets)))

    if len(means) >= 3:
        monotonic = all(means[i][1] >= means[i+1][1] for i in range(len(means)-1))
        lines.append(f"Tier order: {' > '.join(f'{t}({m:+.1%})' for t, m in means)}")
        if monotonic:
            lines.append("\nMonotonicity: PASS — higher tiers have higher returns")
        else:
            lines.append("\nMonotonicity: FAIL — tier ordering does not match return ordering")
            lines.append("**ACTION REQUIRED:** Recalibrate tier thresholds in composite_engine.py")

    # Recommendations
    lines.append("\n## Recommendations\n")
    conv = tier_rets.get("CONVICTION", [])
    watch = tier_rets.get("WATCH", [])
    if len(conv) >= 3 and len(watch) >= 3:
        _, p = welch_t(conv, watch)
        if p < 0.05:
            lines.append("1. CONVICTION tier significantly outperforms WATCH — scoring is calibrated")
        else:
            lines.append("1. CONVICTION vs WATCH is NOT significant — consider:")
            lines.append("   - Adjusting tier thresholds in composite_engine.py")
            lines.append("   - Reweighting lens contributions (LENS_WEIGHTS)")
            lines.append("   - Adding data: more snapshots will increase statistical power")

    lines.append("")
    return "\n".join(lines)


async def main_async(args):
    report = await calibration(args.horizon)
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        logger.info(f"Calibration report written to {args.output}")
    else:
        print(report)


def main():
    parser = argparse.ArgumentParser(description="Generate calibration report")
    parser.add_argument("--horizon", type=int, default=90, help="Return horizon in days")
    parser.add_argument("--output", type=str, default=None, help="Output file")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
