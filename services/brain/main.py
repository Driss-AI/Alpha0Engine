"""
Brain Worker — Main Entry Point
=================================
Runs the AI Brain pipeline: scan candidates → collect evidence →
Claude analysis → verify citations → threshold gate → persist.

Modes:
  RUN_MODE=once  — single run then exit (Railway cron)
  RUN_MODE=loop  — run every 24h (default)
"""
import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from brain_core import run_brain
from feedback import run_feedback

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("brain.worker")


async def run_once():
    logger.info("Brain worker starting (mode=once)")
    stats = await run_brain()
    logger.info(
        f"Brain run complete: {stats['threshold_passed']} opportunities published, "
        f"{stats['analyzed']} analyzed, {len(stats['errors'])} errors"
    )

    logger.info("Running feedback loop on past picks...")
    fb_stats = await run_feedback()
    logger.info(
        f"Feedback complete: {fb_stats['newly_hit']} hit, "
        f"{fb_stats['newly_missed']} miss, {fb_stats['unchanged']} unchanged"
    )
    return stats


async def run_loop():
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.error(f"Brain run failed: {e}", exc_info=True)
        logger.info("Next brain run in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("brain", run_once))
    else:
        asyncio.run(run_loop())
