"""
Screener — one scoring pass (RESTRUCTURE.md §2).
================================================
Merge of the former fundamental-screener / risk-filter / screener-1000x
services. Phases run in sequence over the same universe:

  1. fundamentals — moat + financial metrics → fundamental_scores
  2. risk         — hype, illiquidity, composite risk → risk_assessments
  3. lenses       — 5 lenses → composite → axes → bucket → equity_screens
                    (+ evidence, catalysts, daily snapshots)
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from shared.logging import setup_logging, get_logger

setup_logging("screener")
logger = get_logger("screener")


async def run_screener():
    """Run all three scoring phases in order."""
    from fundamentals import run_screening_batch as run_fundamentals
    from risk import run_risk_batch
    from lenses import run_screening_batch as run_lenses

    logger.info("SCREENER — fundamentals → risk → lenses")
    await run_fundamentals()
    await run_risk_batch()
    await run_lenses()
    logger.info("SCREENER COMPLETE")


if __name__ == "__main__":
    if os.environ.get("RUN_MODE", "once") == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("screener", run_screener))
    else:
        asyncio.run(run_screener())
