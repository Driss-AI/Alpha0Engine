"""GitHub Archive Ingest Worker — hourly at :05"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging, schedule, time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from gh_archive_client import GitHubArchiveClient

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL","INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ingest-github")

# Tracked orgs — expanded dynamically from entities DB
TRACKED_ORGS = {
    "openai": "openai", "mistralai": "mistralai",
    "huggingface": "huggingface", "langchain-ai": "langchain",
    "anthropics-public": "anthropic",
}


def run_hourly_ingest():
    target = datetime.utcnow() - timedelta(hours=2)
    log.info(f"GH Archive: {target.strftime('%Y-%m-%d %H:00')}")
    client = GitHubArchiveClient()
    events = client.fetch_hour(target)
    relevant = client.filter_relevant(events, TRACKED_ORGS)
    log.info(f"Total: {len(events)} Relevant: {len(relevant)}")
    for event in relevant:
        try:
            client.process_event(event, TRACKED_ORGS)
        except Exception as e:
            log.error(f"Event error {event.get('id')}: {e}")
    log.info("GH Archive ingest complete.")


def main():
    log.info("GitHub Archive worker starting...")

    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        log.info("RUN_MODE=once — running single ingest then exiting")
        run_hourly_ingest()
        log.info("GitHub Archive ingest complete. Exiting.")
        return

    run_hourly_ingest()
    schedule.every().hour.at(":05").do(run_hourly_ingest)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
