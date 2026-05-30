"""
News Ingestion Worker
======================
Fetches financial news for tracked public tickers and stores
in company_news table. Used by the Brain as evidence.

Sources:
  1. Finnhub Company News (free tier: 60 calls/min)

Runs daily. Fetches news from the last 3 days to catch
anything missed and deduplicates by URL.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.entities import Entity
from shared.schemas.company_news import CompanyNews

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest-news")

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"
LOOKBACK_DAYS = 3
RATE_LIMIT_DELAY = 1.1  # finnhub free = 60 calls/min
BATCH_SIZE = 50

# ── Keyword-based sentiment ──────────────────────────────────
BULLISH_KEYWORDS = {
    "beat", "beats", "exceeded", "upgrade", "upgrades", "raised",
    "positive", "growth", "surges", "soars", "breakthrough", "approval",
    "approved", "partnership", "contract", "wins", "profit", "bullish",
    "outperform", "buy", "strong", "record", "accelerat",
}
BEARISH_KEYWORDS = {
    "miss", "missed", "downgrade", "downgrades", "cut", "cuts",
    "negative", "decline", "falls", "plunges", "lawsuit", "recall",
    "warning", "loss", "bearish", "underperform", "sell", "weak",
    "delay", "delayed", "failure", "failed", "investigation",
}
CATEGORY_KEYWORDS = {
    "earnings": {"earnings", "eps", "revenue", "quarterly", "q1", "q2", "q3", "q4", "profit", "income"},
    "fda": {"fda", "approval", "drug", "trial", "clinical", "phase", "nda", "bla"},
    "merger": {"merger", "acquisition", "acquire", "takeover", "buyout", "deal"},
    "offering": {"offering", "ipo", "secondary", "dilution", "shelf"},
    "insider": {"insider", "ceo", "cfo", "director", "buyback", "repurchase"},
    "legal": {"lawsuit", "settlement", "investigation", "sec", "doj", "fraud"},
}


def _classify_sentiment(title: str, summary: str) -> tuple:
    """Simple keyword-based sentiment. Returns (label, score)."""
    text = f"{title} {summary}".lower()
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    total = bull + bear
    if total == 0:
        return "neutral", 0.0
    score = (bull - bear) / total
    if score > 0.2:
        return "bullish", min(score, 1.0)
    elif score < -0.2:
        return "bearish", max(score, -1.0)
    return "neutral", score


def _classify_categories(title: str, summary: str) -> List[str]:
    text = f"{title} {summary}".lower()
    cats = []
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            cats.append(cat)
    return cats


async def _get_tracked_tickers(session: AsyncSession) -> List[Dict[str, str]]:
    """Get all public tickers we're tracking."""
    result = await session.exec(
        select(Entity.id, Entity.ticker, Entity.name)
        .where(Entity.entity_type == "public", Entity.ticker.isnot(None))
    )
    return [{"entity_id": r[0], "ticker": r[1], "name": r[2]} for r in result.all()]


async def _get_existing_urls(session: AsyncSession, urls: Set[str]) -> Set[str]:
    """Check which URLs already exist in DB."""
    if not urls:
        return set()
    result = await session.exec(
        select(CompanyNews.url).where(CompanyNews.url.in_(list(urls)))
    )
    return set(result.all())


async def _fetch_finnhub_news(
    client: httpx.AsyncClient,
    ticker: str,
    from_date: str,
    to_date: str,
) -> List[Dict[str, Any]]:
    """Fetch news from Finnhub for a single ticker."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker,
                "from": from_date,
                "to": to_date,
                "token": FINNHUB_KEY,
            },
            timeout=15,
        )
        if resp.status_code == 429:
            logger.warning(f"  Finnhub rate limited on {ticker}, sleeping 60s")
            await asyncio.sleep(60)
            return []
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"  Finnhub error for {ticker}: {e}")
        return []


async def ingest_news_batch(
    session: AsyncSession,
    tickers: List[Dict[str, str]],
) -> Dict[str, int]:
    """Fetch and store news for a batch of tickers."""
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    to_date = today.isoformat()

    stats = {"fetched": 0, "new": 0, "duplicates": 0, "errors": 0}

    async with httpx.AsyncClient() as client:
        for entity in tickers:
            ticker = entity["ticker"]
            entity_id = entity["entity_id"]
            company_name = entity["name"]

            articles = await _fetch_finnhub_news(client, ticker, from_date, to_date)
            stats["fetched"] += len(articles)

            if not articles:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                continue

            urls = {a.get("url", "") for a in articles if a.get("url")}
            existing_urls = await _get_existing_urls(session, urls)

            for article in articles:
                url = article.get("url", "")
                if not url or url in existing_urls:
                    stats["duplicates"] += 1
                    continue

                title = article.get("headline", "")
                summary = article.get("summary", "")
                sentiment, sentiment_score = _classify_sentiment(title, summary)
                categories = _classify_categories(title, summary)

                pub_ts = article.get("datetime")
                published_at = (
                    datetime.fromtimestamp(pub_ts, tz=timezone.utc).replace(tzinfo=None)
                    if pub_ts else None
                )

                try:
                    news = CompanyNews(
                        entity_id=entity_id,
                        ticker=ticker,
                        company_name=company_name,
                        title=title[:500] if title else "",
                        summary=summary[:2000] if summary else None,
                        url=url,
                        source=article.get("source", "finnhub"),
                        author=None,
                        sentiment=sentiment,
                        sentiment_score=sentiment_score,
                        relevance_score=None,
                        categories=categories,
                        published_at=published_at,
                        raw_data={
                            "finnhub_id": article.get("id"),
                            "image": article.get("image"),
                            "related": article.get("related"),
                        },
                    )
                    session.add(news)
                    stats["new"] += 1
                    existing_urls.add(url)
                except Exception as e:
                    logger.error(f"  Error storing article for {ticker}: {e}")
                    stats["errors"] += 1

            if stats["new"] % 50 == 0 and stats["new"] > 0:
                await session.flush()

            await asyncio.sleep(RATE_LIMIT_DELAY)

    await session.flush()
    return stats


async def run_ingestion():
    """Main entry point."""
    await create_db_and_tables()

    if not FINNHUB_KEY:
        logger.error("FINNHUB_API_KEY not set — cannot fetch news")
        return

    async with AsyncSessionLocal() as session:
        tickers = await _get_tracked_tickers(session)
        logger.info(f"Found {len(tickers)} tracked public tickers")

        if not tickers:
            logger.info("No tickers to fetch news for")
            return

        total_stats = {"fetched": 0, "new": 0, "duplicates": 0, "errors": 0}

        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i:i + BATCH_SIZE]
            logger.info(f"Processing batch {i // BATCH_SIZE + 1} ({len(batch)} tickers)")

            stats = await ingest_news_batch(session, batch)
            for k in total_stats:
                total_stats[k] += stats[k]

            logger.info(
                f"  Batch done: {stats['fetched']} fetched, "
                f"{stats['new']} new, {stats['duplicates']} dupes"
            )

        await session.commit()

        logger.info("=" * 60)
        logger.info("NEWS INGESTION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Tickers processed: {len(tickers)}")
        logger.info(f"  Articles fetched:  {total_stats['fetched']}")
        logger.info(f"  New stored:        {total_stats['new']}")
        logger.info(f"  Duplicates:        {total_stats['duplicates']}")
        logger.info(f"  Errors:            {total_stats['errors']}")


async def run_loop():
    while True:
        try:
            await run_ingestion()
        except Exception as e:
            logger.error(f"News ingestion failed: {e}", exc_info=True)
        logger.info("Next news ingestion in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("ingest-news", run_ingestion))
    else:
        asyncio.run(run_loop())
