#!/usr/bin/env python3
"""Wipe ALL Alpha0Engine data tables for a clean-slate rescan.

Truncates every application data table (entities, signals, screens, snapshots,
watchlist, alerts, …) while leaving the schema and `alembic_version` untouched,
so the next `scripts/run_daily_pipeline.py` run repopulates from scratch.

Refuses to run unless explicitly confirmed with --yes or WIPE_CONFIRM=yes.

Usage:
    python scripts/wipe_data.py --yes
    WIPE_CONFIRM=yes python scripts/wipe_data.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from shared.clients.postgres import engine  # noqa: E402

# Every application data table. alembic_version is deliberately absent.
DATA_TABLES = [
    "signals",
    "equity_screens",
    "score_snapshots",
    "user_watchlist",
    "catalyst_events",
    "risk_assessments",
    "alerts",
    "candidate_lanes",
    "daily_prices",
    "company_news",
    "clinical_trials",
    "fda_events",
    "fundamental_scores",
    "evidence_items",
    "ingestion_runs",
    "ticker_timeline",
    "data_freshness",
    "pipeline_health",
    "market_context_signals",
    "score_validations",
    "hyperscaler_capex",
    "entities",
]


async def wipe() -> None:
    async with engine.begin() as conn:
        existing = await conn.run_sync(lambda sc: set(inspect(sc).get_table_names()))
        targets = [t for t in DATA_TABLES if t in existing]
        missing = [t for t in DATA_TABLES if t not in existing]
        if not targets:
            print("nothing to wipe — no known data tables found")
            return

        counts: dict[str, int] = {}
        for t in targets:
            counts[t] = (await conn.execute(text(f'SELECT COUNT(*) FROM "{t}"'))).scalar_one()

        if engine.dialect.name == "postgresql":
            quoted = ", ".join(f'"{t}"' for t in targets)
            await conn.execute(text(f"TRUNCATE {quoted} CASCADE"))
        else:  # sqlite (tests/local) has no TRUNCATE
            for t in targets:
                await conn.execute(text(f'DELETE FROM "{t}"'))

        for t in targets:
            print(f"  wiped {t:<26} ({counts[t]} rows)")
        if missing:
            print(f"  (not present, skipped: {', '.join(missing)})")
        print(f"total rows deleted: {sum(counts.values())}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the wipe")
    args = parser.parse_args(argv)

    confirmed = args.yes or os.environ.get("WIPE_CONFIRM", "").strip().lower() in ("1", "true", "yes")
    if not confirmed:
        print("refusing to wipe: pass --yes or set WIPE_CONFIRM=yes", file=sys.stderr)
        return 2

    asyncio.run(wipe())
    print("wipe complete — schema and alembic_version untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
