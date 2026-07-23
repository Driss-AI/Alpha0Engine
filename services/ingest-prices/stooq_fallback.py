"""
Stooq + SEC fallback price source
=================================
Yahoo Finance rate-limits/blocks cloud-provider IPs (observed on Railway:
every yfinance call returns an empty body and the daily run stores 0 price
rows). This module provides a keyless fallback so the engine still gets an
end-of-day snapshot for the whole universe:

  - OHLCV:  Stooq bulk quote CSV (https://stooq.com/q/l/) — batched symbols,
            one EOD row per ticker, no API key.
  - Shares: SEC XBRL "frames" API — one bulk request returns shares
            outstanding for every filer in a quarter, keyed by CIK.
  - Market cap = close x shares outstanding.

Both sources are best-effort: any failure returns partial/empty data and the
caller keeps whatever yfinance managed to fetch.
"""
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/l/"
STOOQ_BATCH = 50          # symbols per request (comma-separated)
STOOQ_PAUSE_S = 0.7       # courtesy pause between requests
FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{frame}.json"
SEC_USER_AGENT = "Alpha0Engine hafid.ellotfi@gmail.com"


def _parse_stooq_csv(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse a Stooq /q/l/ CSV (f=sd2t2ohlcv&h) into {TICKER: record}."""
    out: Dict[str, Dict[str, Any]] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if line.lower().startswith("symbol,"):
            continue  # header
        parts = line.split(",")
        if len(parts) < 8:
            continue
        symbol, d, _t, o, h, low, c, v = parts[:8]
        ticker = symbol.upper().removesuffix(".US")

        def num(x: str) -> Optional[float]:
            try:
                return float(x)
            except (TypeError, ValueError):
                return None  # "N/D" etc.

        close = num(c)
        if close is None or close <= 0:
            continue
        try:
            trade_date = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            trade_date = date.today()
        out[ticker] = {
            "ticker": ticker,
            "trade_date": trade_date,
            "open": num(o),
            "high": num(h),
            "low": num(low),
            "close": round(close, 4),
            "volume": num(v),
            "change_pct": None,
            "change_5d_pct": None,
            "change_20d_pct": None,
            "avg_volume_10d": None,
            "avg_volume_30d": None,
            "is_penny": close < 5.0,
            "is_micro": close < 50.0,
        }
    return out


def fetch_stooq_quotes(tickers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Bulk EOD snapshot for `tickers`. Returns {ticker: [one_day_record]}.

    Mirrors fetch_batch_prices' return shape (list of day records) so the
    caller can treat both sources identically; Stooq only gives the latest
    session, so each list has a single record.
    """
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not tickers:
        return results

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i in range(0, len(tickers), STOOQ_BATCH):
            batch = tickers[i:i + STOOQ_BATCH]
            symbols = ",".join(f"{t.lower()}.us" for t in batch)
            try:
                resp = client.get(
                    STOOQ_URL,
                    params={"s": symbols, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                )
                body = resp.text or ""
                if resp.status_code != 200:
                    logger.warning(f"Stooq batch {i // STOOQ_BATCH + 1}: HTTP {resp.status_code}")
                    continue
                if "daily hits limit" in body.lower():
                    logger.warning("Stooq daily hits limit reached — stopping fallback fetch")
                    break
                for ticker, rec in _parse_stooq_csv(body).items():
                    results[ticker] = [rec]
            except Exception as e:
                logger.warning(f"Stooq batch {i // STOOQ_BATCH + 1} failed: {e}")
            time.sleep(STOOQ_PAUSE_S)

    logger.info(f"Stooq fallback: quotes for {len(results)}/{len(tickers)} tickers")
    return results


def _candidate_frames(today: Optional[date] = None) -> List[str]:
    """Instantaneous share-count frames, newest first (current + 3 back)."""
    today = today or date.today()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    frames = []
    for _ in range(4):
        frames.append(f"CY{year}Q{quarter}I")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return frames


def fetch_sec_shares_outstanding() -> Dict[str, float]:
    """Bulk shares outstanding for every SEC filer: {cik(no leading zeros): shares}.

    Tries the current quarter's frame first, stepping back up to a year until
    a frame has data (frames publish with a lag).
    """
    headers = {"User-Agent": SEC_USER_AGENT}
    for frame in _candidate_frames():
        try:
            resp = httpx.get(FRAMES_URL.format(frame=frame), headers=headers, timeout=60)
            if resp.status_code != 200:
                continue
            rows = resp.json().get("data") or []
            if not rows:
                continue
            out: Dict[str, float] = {}
            for row in rows:
                cik = row.get("cik")
                val = row.get("val")
                if cik is not None and val:
                    out[str(int(cik))] = float(val)
            logger.info(f"SEC frames {frame}: shares outstanding for {len(out)} filers")
            return out
        except Exception as e:
            logger.warning(f"SEC frames {frame} fetch failed: {e}")
    logger.warning("SEC frames: no share data found in the last 4 quarters")
    return {}
