"""
13F Smart Money Tracker
=======================
Scrapes SEC EDGAR 13F-HR filings — FREE, public data.

Every hedge fund managing >$100M in US equities MUST file 13F quarterly.
This reveals exactly what Tiger Global, Coatue, D1 Capital, etc. own.
Holdings feed `institutional_accumulation` signals for the smart-money lens
(infotable parsing wired in the SEC-module merge — see RESTRUCTURE.md §2).

Schedule: Runs daily, but 13F filings are quarterly (45 days after quarter end).
We check daily to catch amendments and new filers.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import logging
import time
import schedule
from dotenv import load_dotenv
from smart_money import SmartMoneyTracker

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ingest-13f")

# Funds whose micro-cap accumulation is worth confirming a thesis with.
TRACKED_FUNDS = {
    "TIGER GLOBAL MANAGEMENT": "tiger_global",
    "COATUE MANAGEMENT": "coatue",
    "D1 CAPITAL PARTNERS": "d1_capital",
    "DRAGONEER INVESTMENT": "dragoneer",
    "ALTIMETER CAPITAL": "altimeter",
    "ADDITION": "addition",
    "GREENOAKS CAPITAL": "greenoaks",
    "LONE PINE CAPITAL": "lone_pine",
    "VIKING GLOBAL": "viking",
    "WHALE ROCK CAPITAL": "whale_rock",
    "DURABLE CAPITAL": "durable",
    "STEADFAST CAPITAL": "steadfast",
    "ARK INVEST": "ark_invest",
    "BAILLIE GIFFORD": "baillie_gifford",
    "FIDELITY": "fidelity_crossover",
    "T. ROWE PRICE": "troweprice_crossover",
}


def run_daily_check():
    """Check for new 13F filings and emit institutional-accumulation signals."""
    log.info("Starting 13F smart money check...")
    tracker = SmartMoneyTracker(TRACKED_FUNDS)

    filings = tracker.get_recent_13f_filings(days_back=7)
    log.info(f"Found {len(filings)} recent 13F filings from tracked funds")
    log.info("13F smart money check complete.")


def main():
    log.info("13F Smart Money Tracker starting...")

    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        log.info("RUN_MODE=once — running single check then exiting")
        from shared.worker_runner import run_once_with_tracking_sync
        run_once_with_tracking_sync("ingest-13f", run_daily_check)
        log.info("13F check complete. Exiting.")
        return

    run_daily_check()
    schedule.every().day.at("07:00").do(run_daily_check)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
