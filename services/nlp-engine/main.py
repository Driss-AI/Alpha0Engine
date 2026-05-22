"""
NLP Engine — Megatrend Detection + IPO Proximity Scoring
=========================================================
Runs on a 6-hour cycle:
  1. Pull new patent abstracts, Form D descriptions, signals
  2. Generate embeddings via sentence-transformers (CPU, no GPU needed)
  3. Store in pgvector for semantic search
  4. Cluster embeddings with HDBSCAN to detect themes
  5. Score theme velocity (growth rate over time)
  6. Score IPO proximity for private companies
  7. Write theme + IPO signals to Redis stream

All free data. No paid APIs. Runs on Railway CPU.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging, schedule, time, asyncio
from dotenv import load_dotenv
from embedder import Embedder
from theme_detector import ThemeDetector
from ipo_scorer import IPOProximityScorer

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("nlp-engine")


async def run_nlp_cycle():
    """Full NLP pipeline — runs every 6 hours."""
    log.info("=== NLP Engine cycle starting ===")

    # Step 1: Generate embeddings for new signals
    embedder = Embedder()
    new_count = await embedder.embed_new_signals()
    log.info(f"Embedded {new_count} new texts")

    # Step 2: Detect/update themes via clustering
    detector = ThemeDetector()
    themes = await detector.detect_themes()
    log.info(f"Detected {len(themes)} active themes")

    # Step 3: Score IPO proximity for private entities
    ipo_scorer = IPOProximityScorer()
    ipo_candidates = await ipo_scorer.score_all()
    log.info(f"Scored {len(ipo_candidates)} IPO proximity candidates")

    log.info("=== NLP Engine cycle complete ===")


def main():
    log.info("NLP Engine starting...")

    # Run immediately, then every 6 hours
    asyncio.get_event_loop().run_until_complete(run_nlp_cycle())
    schedule.every(6).hours.do(lambda: asyncio.get_event_loop().run_until_complete(run_nlp_cycle()))

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
