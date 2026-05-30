#!/usr/bin/env python3
"""
Backtest Analysis — Conviction Tier vs Actual Returns
=====================================================
Reads score_validations and produces a markdown report showing
how each conviction tier performed at each time horizon.

Usage:
    python scripts/backtest_analyze.py                  # full report
    python scripts/backtest_analyze.py --output report.md  # save to file
    python scripts/backtest_analyze.py --min-samples 10    # require N samples per tier

Requires: score_validations table populated by backtest_dataset.py
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date
from math import sqrt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.score_validation import ScoreValidation
from shared.logging import setup_logging, get_logger

setup_logging("backtest-analyze")
logger = get_logger("backtest-analyze")

TIERS = ["CONVICTION", "HIGH", "WATCH", "SPECULATIVE", "PASS"]
HORIZONS = [30, 90, 180, 365]


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def _win_rate(outcomes: list[str]) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o == "win") / len(outcomes)


def _t_test_two_sample(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t-test. Returns (t_stat, p_value_approx)."""
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0

    ma, mb = _mean(a), _mean(b)
    sa, sb = _std(a), _std(b)
    na, nb = len(a), len(b)

    se = sqrt((sa ** 2 / na) + (sb ** 2 / nb)) if (sa > 0 or sb > 0) else 1e-10
    t_stat = (ma - mb) / se if se > 0 else 0.0

    # Approximate p-value using normal distribution for large samples
    from math import erf
    p_value = 1.0 - erf(abs(t_stat) / sqrt(2))
    return round(t_stat, 3), round(p_value, 4)


async def analyze(min_samples: int, lane: str | None = None) -> str:
    lines = []
    lines.append("# Alpha0Engine — Backtest Analysis Report")
    lines.append(f"\nGenerated: {date.today()}")
    if lane:
        lines.append(f"**Lane:** {lane}")
    lines.append(f"Minimum samples per tier: {min_samples}\n")

    async with AsyncSessionLocal() as session:
        query = select(ScoreValidation)
        if lane:
            query = query.where(ScoreValidation.lane_id == lane)
        rows = (await session.exec(query)).all()

    if not rows:
        scope = f" for lane {lane}" if lane else ""
        return f"No score_validation data found{scope}. Run backtest_dataset.py first."

    lines.append(f"**Total validation records:** {len(rows)}\n")

    # Group by tier
    by_tier: dict[str, list[ScoreValidation]] = defaultdict(list)
    for r in rows:
        by_tier[r.conviction_tier].append(r)

    # Tier distribution
    lines.append("## Tier Distribution\n")
    lines.append("| Tier | Count | % |")
    lines.append("|------|------:|--:|")
    for tier in TIERS:
        count = len(by_tier.get(tier, []))
        pct = round(count / len(rows) * 100, 1) if rows else 0
        lines.append(f"| {tier} | {count} | {pct}% |")

    # Returns by tier per horizon
    for horizon in HORIZONS:
        field = f"return_{horizon}d"
        outcome_field = f"outcome_{horizon}d"

        lines.append(f"\n## {horizon}-Day Returns by Tier\n")
        lines.append("| Tier | N | Mean | Median | Std | Win Rate | Wins | Losses | Flat |")
        lines.append("|------|--:|-----:|-------:|----:|---------:|-----:|-------:|-----:|")

        tier_returns: dict[str, list[float]] = {}

        for tier in TIERS:
            entries = by_tier.get(tier, [])
            returns = [getattr(r, field) for r in entries if getattr(r, field) is not None]
            outcomes = [getattr(r, outcome_field) for r in entries if getattr(r, outcome_field) is not None]
            tier_returns[tier] = returns

            n = len(returns)
            if n < min_samples:
                lines.append(f"| {tier} | {n} | — | — | — | — | — | — | — |")
                continue

            mean = _mean(returns)
            med = _median(returns)
            std = _std(returns)
            wr = _win_rate(outcomes)
            wins = sum(1 for o in outcomes if o == "win")
            losses = sum(1 for o in outcomes if o == "loss")
            flat = sum(1 for o in outcomes if o == "flat")

            lines.append(
                f"| {tier} | {n} | {mean:+.1%} | {med:+.1%} | {std:.1%} "
                f"| {wr:.0%} | {wins} | {losses} | {flat} |"
            )

        # Statistical test: CONVICTION vs WATCH
        conv_rets = tier_returns.get("CONVICTION", [])
        watch_rets = tier_returns.get("WATCH", [])
        if len(conv_rets) >= min_samples and len(watch_rets) >= min_samples:
            t_stat, p_val = _t_test_two_sample(conv_rets, watch_rets)
            sig = "YES" if p_val < 0.05 else "NO"
            lines.append(
                f"\n**CONVICTION vs WATCH ({horizon}d):** "
                f"t={t_stat}, p={p_val} — Significant: {sig}"
            )

    # Score correlation
    lines.append("\n## Score vs Return Correlation\n")
    for horizon in HORIZONS:
        field = f"return_{horizon}d"
        scores = []
        returns = []
        for r in rows:
            ret = getattr(r, field)
            if ret is not None:
                scores.append(r.composite_score)
                returns.append(ret)

        if len(scores) < 10:
            lines.append(f"- **{horizon}d:** insufficient data (n={len(scores)})")
            continue

        # Pearson correlation
        n = len(scores)
        ms, mr = _mean(scores), _mean(returns)
        num = sum((s - ms) * (r - mr) for s, r in zip(scores, returns))
        den_s = sqrt(sum((s - ms) ** 2 for s in scores))
        den_r = sqrt(sum((r - mr) ** 2 for r in returns))
        corr = num / (den_s * den_r) if (den_s > 0 and den_r > 0) else 0.0

        lines.append(f"- **{horizon}d:** r={corr:.3f} (n={n})")

    # Top lens performance
    lines.append("\n## Performance by Top Lens (90-day returns)\n")
    lines.append("| Lens | N | Mean | Median | Win Rate |")
    lines.append("|------|--:|-----:|-------:|---------:|")

    WIN_THRESHOLD = 0.10
    by_lens: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.top_lens and r.return_90d is not None:
            by_lens[r.top_lens].append(r.return_90d)

    for lens in sorted(by_lens.keys()):
        rets = by_lens[lens]
        if len(rets) < min_samples:
            continue
        mean = _mean(rets)
        med = _median(rets)
        wr = sum(1 for r in rets if r >= WIN_THRESHOLD) / len(rets)
        lines.append(f"| {lens} | {len(rets)} | {mean:+.1%} | {med:+.1%} | {wr:.0%} |")

    # Summary
    lines.append("\n## Key Findings\n")
    conv_90 = tier_returns.get("CONVICTION", []) if "tier_returns" in dir() else []
    pass_90 = tier_returns.get("PASS", []) if "tier_returns" in dir() else []

    if conv_90 and pass_90:
        conv_mean = _mean(conv_90)
        pass_mean = _mean(pass_90)
        if conv_mean > pass_mean:
            lines.append(
                f"- CONVICTION tier outperforms PASS by "
                f"{(conv_mean - pass_mean):+.1%} at 90 days"
            )
        else:
            lines.append(
                f"- WARNING: CONVICTION tier does NOT outperform PASS "
                f"({conv_mean:+.1%} vs {pass_mean:+.1%}) — scoring needs recalibration"
            )

    lines.append("")
    return "\n".join(lines)


async def main_async(args):
    report = await analyze(args.min_samples, args.lane)
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        logger.info(f"Report written to {args.output}")
    else:
        print(report)


def main():
    parser = argparse.ArgumentParser(description="Analyze backtest results")
    parser.add_argument("--min-samples", type=int, default=5, help="Minimum samples per tier")
    parser.add_argument("--lane", default=None, help="Filter to one lane (L1_AI_INFRA / L2_BIOTECH)")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
