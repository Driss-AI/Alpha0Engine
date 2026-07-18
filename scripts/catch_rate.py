#!/usr/bin/env python3
"""
Catch-rate scoreboard CLI — "would we have caught it?"

Runs the archetype cases in services/screener/catch_rate_cases.py through the
engine's real scoring path and prints the scoreboard. See
services/screener/catch_rate.py for the harness and RESTRUCTURE.md §3.4 for
why this exists.

Usage:
    DATABASE_URL=sqlite+aiosqlite:// python scripts/catch_rate.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "screener"))

from catch_rate import run_all, render_scoreboard  # noqa: E402


def main() -> int:
    summary = run_all()
    print(render_scoreboard(summary))
    missed = summary["n_winners"] - summary["winners_caught"]
    return 1 if (missed or summary["false_positives_flagged"]) else 0


if __name__ == "__main__":
    sys.exit(main())
