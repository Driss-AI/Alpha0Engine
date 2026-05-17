"""USPTO Patent Ingest Worker — weekly Sunday 02:00 UTC"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging, time, schedule
from datetime import datetime, timedelta
from dotenv import load_dotenv
from uspto_client import UsptoClient

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL","INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ingest-patents")


def run_weekly_ingest():
    end = datetime.utcnow()
    start = end - timedelta(days=7)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    log.info(f"USPTO ingest: {s} to {e}")
    client = UsptoClient()
    grants = client.get_patents(s, e, "grant")
    apps = client.get_patents(s, e, "application")
    log.info(f"Grants: {len(grants)} Apps: {len(apps)}")
    for patent in grants + apps:
        try:
            client.process_patent(patent)
            time.sleep(0.1)
        except Exception as ex:
            log.error(f"Patent error {patent.get('patent_id')}: {ex}")
    log.info("USPTO ingest complete.")


def main():
    log.info("USPTO patent worker starting...")
    run_weekly_ingest()
    schedule.every().sunday.at("02:00").do(run_weekly_ingest)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
