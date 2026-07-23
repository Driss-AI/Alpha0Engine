"""
Finnhub quote fallback
======================
Last-resort price source. Unlike Yahoo (blocks cloud IPs) and Stooq
(404s data-center traffic), Finnhub demonstrably works from Railway —
the news ingest uses the same key every run.

Free-tier limit is 60 calls/min, so a full 10k-ticker universe is out of
reach in one run. Instead the caller passes tickers in priority order and
a per-run budget (FINNHUB_QUOTE_BUDGET, default 1800 ≈ 30 min); coverage
accumulates across daily runs.
"""
import logging
import os
import time
from datetime import date
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

QUOTE_URL = "https://finnhub.io/api/v1/quote"
PACE_S = 1.05  # ~57 calls/min, safely under the 60/min free-tier cap


def quote_budget() -> int:
    try:
        return int(os.environ.get("FINNHUB_QUOTE_BUDGET", "1800"))
    except ValueError:
        return 1800


def fetch_finnhub_quotes(tickers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Current-day quotes for up to `quote_budget()` tickers, in given order.

    Returns {ticker: [one_day_record]} in the fetch_batch_prices record shape.
    Silently returns {} when FINNHUB_API_KEY is unset.
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not api_key or not tickers:
        return results

    budget = quote_budget()
    todo = tickers[:budget]
    logger.info(f"Finnhub quote fallback: fetching {len(todo)} tickers "
                f"(budget {budget}, ~{len(todo) * PACE_S / 60:.0f} min)")

    today = date.today()
    errors = 0
    with httpx.Client(timeout=15) as client:
        for ticker in todo:
            try:
                resp = client.get(QUOTE_URL, params={"symbol": ticker, "token": api_key})
                if resp.status_code == 429:
                    logger.warning("Finnhub 429 — sleeping 30s")
                    time.sleep(30)
                    continue
                if resp.status_code != 200:
                    errors += 1
                    continue
                q = resp.json()
                close = q.get("c")
                if not close or close <= 0:
                    continue  # unknown symbol / no trade data
                results[ticker] = [{
                    "ticker": ticker,
                    "trade_date": today,
                    "open": q.get("o") or None,
                    "high": q.get("h") or None,
                    "low": q.get("l") or None,
                    "close": round(float(close), 4),
                    "volume": None,
                    "change_pct": (round(q["dp"] / 100.0, 6)
                                   if isinstance(q.get("dp"), (int, float)) else None),
                    "change_5d_pct": None,
                    "change_20d_pct": None,
                    "avg_volume_10d": None,
                    "avg_volume_30d": None,
                    "is_penny": close < 5.0,
                    "is_micro": close < 50.0,
                }]
            except Exception as e:
                errors += 1
                logger.debug(f"Finnhub quote failed for {ticker}: {e}")
            time.sleep(PACE_S)

    logger.info(f"Finnhub quote fallback: {len(results)}/{len(todo)} tickers "
                f"({errors} errors)")
    return results
