#!/usr/bin/env python3
"""
Seed known historical cases (Sprint 10.1)

Writes `score_snapshots` rows for a curated set of historical winners and false
positives PER LANE, each dated just BEFORE the move, with the lens scores the
engine *would* have produced from evidence available at that date. The backtest
(10.2) then joins these with real `DailyPrice` data to measure forward returns —
answering "would this engine have caught SPRB / BE / SNDK before the move, and
how many false positives would it have fired?"

This is a seed of LABELED cases — the snapshot_date and approximate lens scores
are hand-curated from the public record, not live engine output. They let us
calibrate before the engine has accumulated its own daily snapshots.

Usage:
    python scripts/seed_known_cases.py            # upsert all cases
    python scripts/seed_known_cases.py --dry-run  # print, don't write
    python scripts/seed_known_cases.py --lane L1_AI_INFRA

Requires DATABASE_URL.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


@dataclass
class KnownCase:
    ticker: str
    lane_id: str
    snapshot_date: date          # just before the move (or before the crash, for FPs)
    label: str                   # "winner" | "false_positive"
    # Approximate lens scores from evidence available at snapshot_date (0–1).
    catalyst: float = 0.0
    earnings: float = 0.0
    demand: float = 0.0
    float_: float = 0.0
    smart_money: float = 0.0
    note: str = ""

    def composite(self) -> float:
        # Mirror the rough convergence shape of the composite engine for seeding.
        vals = [self.catalyst, self.earnings, self.demand, self.float_, self.smart_money]
        active = sum(1 for v in vals if v >= 0.30)
        base = sum(vals) / 5.0
        bonus = {0: 0, 1: 0, 2: 0.04, 3: 0.08, 4: 0.12, 5: 0.15}[active]
        return round(min(base + bonus, 1.0), 4)

    def active_lenses(self) -> int:
        vals = [self.catalyst, self.earnings, self.demand, self.float_, self.smart_money]
        return sum(1 for v in vals if v >= 0.30)

    def tier(self) -> str:
        c = self.composite()
        if c > 0.75: return "CONVICTION"
        if c > 0.55: return "HIGH"
        if c > 0.35: return "WATCH"
        if c > 0.15: return "SPECULATIVE"
        return "PASS"


# ── L1 AI Infrastructure ─────────────────────────────────────────────────────
# Winners: companies that re-rated hard on AI-infra demand. Scores reflect what
# was visible BEFORE the move (strong demand + smart money, modest catalyst).
L1_WINNERS = [
    KnownCase("BE",   "L1_AI_INFRA", date(2024, 8, 1),  "winner", catalyst=0.5, demand=0.85, smart_money=0.6, float_=0.4, note="fuel cell power for data centers"),
    KnownCase("VST",  "L1_AI_INFRA", date(2024, 2, 1),  "winner", demand=0.9, earnings=0.7, smart_money=0.65, note="independent power producer, AI demand"),
    KnownCase("CEG",  "L1_AI_INFRA", date(2024, 1, 15), "winner", demand=0.9, earnings=0.6, smart_money=0.6, note="nuclear baseload for AI"),
    KnownCase("IREN", "L1_AI_INFRA", date(2024, 9, 1),  "winner", catalyst=0.6, demand=0.8, float_=0.6, smart_money=0.4, note="miner→GPU hosting pivot"),
    KnownCase("CORZ", "L1_AI_INFRA", date(2024, 6, 1),  "winner", catalyst=0.7, demand=0.8, float_=0.5, smart_money=0.5, note="data center reorg + AI"),
    KnownCase("APLD", "L1_AI_INFRA", date(2024, 5, 1),  "winner", catalyst=0.65, demand=0.75, float_=0.6, note="HPC data center buildout"),
    KnownCase("LITE", "L1_AI_INFRA", date(2024, 3, 1),  "winner", demand=0.8, earnings=0.55, smart_money=0.5, note="optical for AI clusters"),
    KnownCase("COHR", "L1_AI_INFRA", date(2024, 2, 1),  "winner", demand=0.8, earnings=0.6, smart_money=0.55, note="optical/datacom inflection"),
    KnownCase("SNDK", "L1_AI_INFRA", date(2025, 2, 1),  "winner", catalyst=0.5, demand=0.8, earnings=0.6, float_=0.5, note="NAND/storage AI cycle"),
    KnownCase("SMCI", "L1_AI_INFRA", date(2023, 11, 1), "winner", demand=0.9, earnings=0.8, smart_money=0.5, note="AI server demand"),
    KnownCase("NBIS", "L1_AI_INFRA", date(2025, 1, 1),  "winner", catalyst=0.6, demand=0.85, smart_money=0.6, float_=0.4, note="neocloud GPU capacity"),
    KnownCase("VRT",  "L1_AI_INFRA", date(2024, 1, 1),  "winner", demand=0.85, earnings=0.65, smart_money=0.55, note="data center cooling/power"),
]

L1_FALSE_POSITIVES = [
    KnownCase("WISA", "L1_AI_INFRA", date(2024, 3, 1), "false_positive", demand=0.5, float_=0.7, note="AI buzzword, no real bottleneck"),
    KnownCase("GFAI", "L1_AI_INFRA", date(2024, 1, 1), "false_positive", demand=0.6, float_=0.8, note="AI label, no demand proof"),
    KnownCase("BBAI", "L1_AI_INFRA", date(2024, 3, 15), "false_positive", demand=0.6, float_=0.6, catalyst=0.3, note="AI services, choppy"),
    KnownCase("SOUN", "L1_AI_INFRA", date(2024, 3, 1), "false_positive", demand=0.65, float_=0.6, note="voice AI pump/dump"),
    KnownCase("AISP", "L1_AI_INFRA", date(2024, 6, 1), "false_positive", demand=0.55, float_=0.7, note="security AI microcap"),
    KnownCase("LGMK", "L1_AI_INFRA", date(2024, 5, 1), "false_positive", demand=0.4, float_=0.8, note="AI rebrand microcap"),
    KnownCase("AGMH", "L1_AI_INFRA", date(2024, 4, 1), "false_positive", demand=0.5, float_=0.7, note="HPC claim, no execution"),
    KnownCase("NXTT", "L1_AI_INFRA", date(2024, 2, 1), "false_positive", demand=0.5, float_=0.6, note="green AI compute claim"),
    KnownCase("VERB", "L1_AI_INFRA", date(2024, 5, 1), "false_positive", demand=0.45, float_=0.7, note="AI pivot, dilutive"),
    KnownCase("GREE", "L1_AI_INFRA", date(2024, 4, 1), "false_positive", demand=0.5, float_=0.6, note="miner, no AI pivot delivered"),
]

# ── L2 Biotech Catalysts ─────────────────────────────────────────────────────
L2_WINNERS = [
    KnownCase("SPRB", "L2_BIOTECH", date(2023, 11, 1), "winner", catalyst=0.85, float_=0.7, smart_money=0.4, note="the SPRB lesson — Phase trial + low float"),
    KnownCase("RXRX", "L2_BIOTECH", date(2023, 7, 1),  "winner", catalyst=0.6, demand=0.7, smart_money=0.6, note="AI drug discovery, NVDA stake"),
    KnownCase("VKTX", "L2_BIOTECH", date(2024, 2, 1),  "winner", catalyst=0.85, earnings=0.3, float_=0.5, note="obesity Phase 2 data"),
    KnownCase("TGTX", "L2_BIOTECH", date(2023, 9, 1),  "winner", catalyst=0.8, earnings=0.5, smart_money=0.5, note="MS drug approval/launch"),
    KnownCase("VIR",  "L2_BIOTECH", date(2023, 3, 1),  "winner", catalyst=0.7, smart_money=0.5, note="antibody pipeline"),
    KnownCase("CRBP", "L2_BIOTECH", date(2024, 1, 1),  "winner", catalyst=0.85, float_=0.6, note="Phase 2 pulmonary data"),
    KnownCase("MLYS", "L2_BIOTECH", date(2024, 3, 1),  "winner", catalyst=0.8, float_=0.5, smart_money=0.4, note="hypertension Phase 2"),
]

L2_FALSE_POSITIVES = [
    KnownCase("CADL", "L2_BIOTECH", date(2024, 2, 1), "false_positive", catalyst=0.6, float_=0.7, note="trial miss / dilution"),
    KnownCase("ATHA", "L2_BIOTECH", date(2024, 1, 1), "false_positive", catalyst=0.7, float_=0.6, note="Alzheimer's trial failure"),
    KnownCase("CRDF", "L2_BIOTECH", date(2024, 3, 1), "false_positive", catalyst=0.6, float_=0.7, note="press-release pump"),
    KnownCase("ENVB", "L2_BIOTECH", date(2024, 2, 1), "false_positive", catalyst=0.5, float_=0.8, note="serial diluter"),
    KnownCase("COSM", "L2_BIOTECH", date(2024, 1, 15), "false_positive", catalyst=0.4, float_=0.8, note="reverse-split candidate"),
    KnownCase("BIVI", "L2_BIOTECH", date(2024, 4, 1), "false_positive", catalyst=0.6, float_=0.7, note="trial design doubts"),
    KnownCase("VTGN", "L2_BIOTECH", date(2024, 3, 1), "false_positive", catalyst=0.55, float_=0.6, note="Phase 2 miss"),
    KnownCase("CYCC", "L2_BIOTECH", date(2024, 2, 1), "false_positive", catalyst=0.5, float_=0.8, note="chronic diluter"),
    KnownCase("INPX", "L2_BIOTECH", date(2024, 1, 1), "false_positive", catalyst=0.3, float_=0.8, note="non-bio masquerade"),
    KnownCase("OCGN", "L2_BIOTECH", date(2024, 5, 1), "false_positive", catalyst=0.6, float_=0.6, note="gene therapy hype fade"),
]

ALL_CASES = L1_WINNERS + L1_FALSE_POSITIVES + L2_WINNERS + L2_FALSE_POSITIVES


def _print_case(c: KnownCase) -> None:
    print(f"  {c.ticker:6s} {c.lane_id:12s} {c.label:15s} {c.snapshot_date} "
          f"comp={c.composite():.2f} tier={c.tier():11s} — {c.note}")


async def seed(cases, dry_run: bool) -> int:
    if dry_run:
        for c in cases:
            _print_case(c)
        return len(cases)

    from sqlalchemy import select
    from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
    from shared.schemas.score_snapshot import ScoreSnapshot

    await create_db_and_tables()

    written = 0
    async with AsyncSessionLocal() as session:
        for c in cases:
            _print_case(c)
            existing = (await session.execute(
                select(ScoreSnapshot).where(
                    ScoreSnapshot.ticker == c.ticker,
                    ScoreSnapshot.snapshot_date == c.snapshot_date,
                )
            )).scalar_one_or_none()
            fields = dict(
                ticker=c.ticker, lane_id=c.lane_id, snapshot_date=c.snapshot_date,
                composite_score=c.composite(), catalyst_score=c.catalyst, earnings_score=c.earnings,
                demand_score=c.demand, float_score=c.float_, smart_money_score=c.smart_money,
                active_lenses=c.active_lenses(), conviction_tier=c.tier(),
            )
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                session.add(existing)
            else:
                session.add(ScoreSnapshot(**fields))
            written += 1
        await session.commit()
    return written


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lane", help="Only seed one lane (L1_AI_INFRA / L2_BIOTECH)")
    args = p.parse_args()

    cases = [c for c in ALL_CASES if not args.lane or c.lane_id == args.lane]
    winners = sum(1 for c in cases if c.label == "winner")
    fps = sum(1 for c in cases if c.label == "false_positive")
    print(f"\nSeeding {len(cases)} known cases ({winners} winners, {fps} false positives)"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")
    written = asyncio.run(seed(cases, args.dry_run))
    print(f"\n{'Would write' if args.dry_run else 'Wrote'} {written} score_snapshots rows.")
    print("Next: run scripts/backtest_dataset.py to join with prices, then "
          "backtest_analyze.py --lane <id>.")


if __name__ == "__main__":
    main()
