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

STOOQ_HOSTS = ("https://stooq.com/q/l/", "https://stooq.pl/q/l/")
STOOQ_BATCH = 20          # symbols per request (comma-separated)
STOOQ_PAUSE_S = 0.7       # courtesy pause between requests
# Stooq 404s plain library user agents from data-center IPs; look like a browser.
STOOQ_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
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


class _StooqLimitReached(Exception):
    """Raised when Stooq reports the daily hits limit — abort remaining work."""


def _stooq_get(
    client: httpx.Client, batch: List[str], host: str = STOOQ_HOSTS[0]
) -> Dict[str, Dict[str, Any]]:
    """One /q/l/ request for a batch. The endpoint is a legacy CGI that 404s
    on percent-encoded commas, so the query string is built by hand (literal
    commas, bare `h` flag)."""
    symbols = ",".join(f"{t.lower()}.us" for t in batch)
    url = f"{host}?s={symbols}&f=sd2t2ohlcv&h&e=csv"
    resp = client.get(url)
    body = resp.text or ""
    if "daily hits limit" in body.lower():
        raise _StooqLimitReached()
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return _parse_stooq_csv(body)


def _fetch_batch_with_split(
    client: httpx.Client,
    batch: List[str],
    results: Dict[str, List[Dict[str, Any]]],
    host: str = STOOQ_HOSTS[0],
) -> None:
    """Fetch one batch; on failure bisect (some symbols 404 whole requests)."""
    try:
        for ticker, rec in _stooq_get(client, batch, host).items():
            results[ticker] = [rec]
    except _StooqLimitReached:
        raise
    except Exception as e:
        if len(batch) == 1:
            logger.debug(f"Stooq gave up on {batch[0]}: {e}")
            return
        mid = len(batch) // 2
        time.sleep(STOOQ_PAUSE_S)
        _fetch_batch_with_split(client, batch[:mid], results, host)
        time.sleep(STOOQ_PAUSE_S)
        _fetch_batch_with_split(client, batch[mid:], results, host)


def fetch_stooq_quotes(tickers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Bulk EOD snapshot for `tickers`. Returns {ticker: [one_day_record]}.

    Mirrors fetch_batch_prices' return shape (list of day records) so the
    caller can treat both sources identically; Stooq only gives the latest
    session, so each list has a single record.
    """
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not tickers:
        return results

    with httpx.Client(timeout=30, follow_redirects=True, headers=STOOQ_HEADERS) as client:
        # Probe each host with one liquid symbol: if none serves data, the
        # endpoint is blocked and there is no point hammering it 500 times.
        host = None
        for candidate in STOOQ_HOSTS:
            try:
                if _stooq_get(client, ["AAPL"], candidate):
                    host = candidate
                    break
            except Exception as e:
                logger.warning(f"Stooq probe on {candidate} failed: {e}")
        if not host:
            logger.warning("Stooq unreachable on all hosts — skipping fallback")
            return results

        try:
            for i in range(0, len(tickers), STOOQ_BATCH):
                _fetch_batch_with_split(client, tickers[i:i + STOOQ_BATCH], results, host)
                time.sleep(STOOQ_PAUSE_S)
        except _StooqLimitReached:
            logger.warning("Stooq daily hits limit reached — stopping fallback fetch")

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
    """Bulk shares outstanding by CIK (no leading zeros), merged across the
    last 4 quarterly frames.

    A single instantaneous frame is surprisingly sparse (~700 filers — share
    counts scatter across cover-date windows), so all four are merged with
    the newest quarter winning. Slightly stale counts are fine: the numbers
    feed market-cap ordering and sizing, not trades.
    """
    headers = {"User-Agent": SEC_USER_AGENT}
    out: Dict[str, float] = {}
    for frame in _candidate_frames():  # newest first — first write wins
        try:
            resp = httpx.get(FRAMES_URL.format(frame=frame), headers=headers, timeout=60)
            if resp.status_code != 200:
                continue
            rows = resp.json().get("data") or []
            added = 0
            for row in rows:
                cik = row.get("cik")
                val = row.get("val")
                if cik is not None and val:
                    key = str(int(cik))
                    if key not in out:
                        out[key] = float(val)
                        added += 1
            logger.info(f"SEC frames {frame}: +{added} filers (total {len(out)})")
        except Exception as e:
            logger.warning(f"SEC frames {frame} fetch failed: {e}")
    if not out:
        logger.warning("SEC frames: no share data found in the last 4 quarters")
    return out
