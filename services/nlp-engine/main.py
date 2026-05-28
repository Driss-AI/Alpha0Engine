"""
NLP Engine — Megatrend Detection + IPO Proximity Scoring
Runs on a 6-hour cycle. All free data.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import logging, schedule, time, asyncio
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("nlp-engine")


async def init_db():
    """Create pgvector extension and embeddings table if they don't exist."""
    from shared.clients.postgres import AsyncSessionLocal
    from sqlmodel import text
    try:
        async with AsyncSessionLocal() as session:
            # Try to enable pgvector — may fail if not installed
            try:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.commit()
                log.info("pgvector extension enabled")
            except Exception as e:
                await session.rollback()
                log.warning(f"pgvector not available (will use basic clustering): {e}")

            # Create tables that SQLModel auto-create might miss
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS themes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    keywords JSON,
                    velocity_score FLOAT DEFAULT 0.0,
                    entity_count INTEGER DEFAULT 0,
                    signal_count INTEGER DEFAULT 0,
                    avg_similarity FLOAT DEFAULT 0.0,
                    status TEXT DEFAULT 'emerging',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS theme_entities (
                    id TEXT PRIMARY KEY,
                    theme_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    similarity_score FLOAT DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT,
                    embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
                    dimensions INTEGER DEFAULT 384,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            # Add vector column only if pgvector is available
            try:
                await session.execute(text("""
                    ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding vector(384)
                """))
            except Exception:
                await session.rollback()
                log.warning("Could not add vector column — pgvector not installed. Using basic mode.")

            await session.commit()
            log.info("Database tables initialized")
    except Exception as e:
        log.error(f"DB init failed: {e}")


async def run_nlp_cycle():
    """Full NLP pipeline."""
    log.info("=== NLP Engine cycle starting ===")

    from embedder import Embedder
    from theme_detector import ThemeDetector
    from ipo_scorer import IPOProximityScorer

    # Step 1: Embed new signals
    try:
        embedder = Embedder()
        new_count = await embedder.embed_new_signals()
        log.info(f"Embedded {new_count} new texts")
    except Exception as e:
        log.error(f"Embedding failed: {e}")

    # Step 2: Detect themes
    try:
        detector = ThemeDetector()
        themes = await detector.detect_themes()
        log.info(f"Detected {len(themes)} active themes")
    except Exception as e:
        log.error(f"Theme detection failed: {e}")

    # Step 3: Score IPO proximity
    try:
        ipo_scorer = IPOProximityScorer()
        candidates = await ipo_scorer.score_all()
        log.info(f"Scored {len(candidates)} IPO candidates")
    except Exception as e:
        log.error(f"IPO scoring failed: {e}")

    log.info("=== NLP Engine cycle complete ===")


def main():
    log.info("NLP Engine starting...")

    # Init DB tables
    asyncio.get_event_loop().run_until_complete(init_db())

    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        log.info("RUN_MODE=once — running single cycle then exiting")
        asyncio.get_event_loop().run_until_complete(run_nlp_cycle())
        log.info("NLP Engine single run complete. Exiting.")
        return

    # Run cycle
    asyncio.get_event_loop().run_until_complete(run_nlp_cycle())
    schedule.every(6).hours.do(lambda: asyncio.get_event_loop().run_until_complete(run_nlp_cycle()))

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
