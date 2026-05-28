"""
EDGAR Form D Ingest Worker — daily 06:00 UTC
Form D filed within 15 days of any private placement >$1M (US).
Pipeline: EFTS query -> XML download -> R2 archive -> Postgres signal -> Redis stream
EDGAR Fair Access: max 10 req/sec, User-Agent required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging, time, asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from edgar_client import EdgarClient
from form_d_parser import parse_form_d

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ingest-edgar")


async def run_daily_ingest():
    from shared.clients.run_tracker import RunTracker

    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    log.info(f"EDGAR Form D ingest for: {yesterday}")

    tracker = RunTracker("ingest-edgar")
    tracker.start()

    client = EdgarClient()
    filings = client.get_form_d_filings(date_str=yesterday)
    log.info(f"Found {len(filings)} filings")

    for filing in filings:
        try:
            xml = client.download_filing(filing["edgar_url"])
            if not xml:
                tracker.record_skip()
                continue
            parsed = parse_form_d(xml, filing)
            if not parsed:
                tracker.record_skip()
                continue
            client.archive_to_r2(parsed, xml, yesterday)
            client.write_signal(parsed)
            client.publish_to_stream(parsed)
            tracker.record_success()
            time.sleep(0.15)
        except Exception as e:
            log.error(f"Error {filing.get('accession_number')}: {e}")
            tracker.record_error(f"{filing.get('accession_number')}: {e}")

    await tracker.finish(metadata={"date": yesterday, "filings_found": len(filings)})


def main():
    log.info("EDGAR worker starting...")

    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        log.info("RUN_MODE=once — running single ingest then exiting")
        asyncio.get_event_loop().run_until_complete(run_daily_ingest())
        log.info("EDGAR ingest complete. Exiting.")
        return

    asyncio.get_event_loop().run_until_complete(run_daily_ingest())
    import schedule
    schedule.every().day.at("06:00").do(lambda: asyncio.get_event_loop().run_until_complete(run_daily_ingest()))
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
