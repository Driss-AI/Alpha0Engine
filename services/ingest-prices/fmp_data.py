"""
Financial Modeling Prep — primary market-data source
====================================================
The engine's two weakest lenses were starved by the free sources it had:

  * Finnhub's /quote returns no volume and no float, so lens 4
    (float_mechanics) had nothing to work with.
  * Float and short interest only ever came from yfinance `.info`, which
    blocks cloud IPs, so on Railway they were always empty.

With 2 of 5 lenses scoring ~0 for every name, nothing could reach conviction —
the last full scan produced CONVICTION 0, HIGH 0 and 0 alertable candidates.

FMP fixes that in two calls per batch:
  - /stable/batch-quote   → price, VOLUME, avgVolume, marketCap (100/call)
  - /stable/shares-float  → float shares + shares outstanding

Everything here is best-effort and keyless-safe: with no FMP_API_KEY set the
functions return {} and the existing Stooq/Finnhub/SEC chain carries on
unchanged.

Response keys are read tolerantly (`_pick`) because FMP has shipped several
naming conventions across its v3/v4/stable endpoints; we accept any of them
rather than breaking on a rename.
"""
import logging
import os
import time
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/stable"
QUOTE_URL = f"{BASE_URL}/batch-quote"
FLOAT_URL = f"{BASE_URL}/shares-float"

QUOTE_BATCH = 100      # symbols per batch-quote call
PACE_S = 0.25          # courtesy pause between calls


def api_key() -> str:
    return os.environ.get("FMP_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(api_key())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def float_budget() -> int:
    """shares-float is one call per symbol, so it is budget-capped like Finnhub."""
    return _int_env("FMP_FLOAT_BUDGET", 2000)


def _pick(row: Dict[str, Any], *keys: str) -> Optional[float]:
    """First present, numeric, non-zero value among `keys`."""
    for k in keys:
        v = row.get(k)
        if v is None or isinstance(v, bool):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f:
            return f
    return None


def _batches(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_fmp_quotes(tickers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Batched EOD quotes with real volume.

    Returns {ticker: [one_day_record]} in the same record shape as
    `fetch_batch_prices`, so callers can merge it straight into `price_data`.
    """
    key = api_key()
    results: Dict[str, List[Dict[str, Any]]] = {}
    if not key or not tickers:
        return results

    today = date.today()
    errors = 0
    batches = list(_batches([t.upper() for t in tickers], QUOTE_BATCH))
    logger.info(f"FMP quotes: {len(tickers)} tickers in {len(batches)} batched calls")

    with httpx.Client(timeout=30) as client:
        for batch in batches:
            try:
                resp = client.get(QUOTE_URL, params={"symbols": ",".join(batch), "apikey": key})
                if resp.status_code == 429:
                    logger.warning("FMP 429 — sleeping 20s")
                    time.sleep(20)
                    continue
                if resp.status_code != 200:
                    errors += 1
                    logger.debug(f"FMP batch-quote {resp.status_code}: {resp.text[:200]}")
                    continue
                payload = resp.json()
                if not isinstance(payload, list):
                    errors += 1
                    logger.debug(f"FMP batch-quote unexpected payload: {str(payload)[:200]}")
                    continue
                for row in payload:
                    rec = _quote_record(row, today)
                    if rec:
                        results[rec["ticker"]] = [rec]
            except Exception as e:
                errors += 1
                logger.debug(f"FMP batch-quote failed: {e}")
            time.sleep(PACE_S)

    logger.info(f"FMP quotes: {len(results)}/{len(tickers)} tickers ({errors} errors)")
    return results


def _quote_record(row: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    symbol = (row.get("symbol") or "").upper().strip()
    close = _pick(row, "price", "close", "previousClose")
    if not symbol or not close or close <= 0:
        return None

    change_pct = _pick(row, "changePercentage", "changesPercentage")
    # FMP reports avgVolume over a trailing window (~3 months); map it to the
    # 30d slot and leave 10d unset rather than inventing a shorter average.
    avg_volume = _pick(row, "avgVolume", "averageVolume", "avgVolume10Day")

    return {
        "ticker": symbol,
        "trade_date": today,
        "open": _pick(row, "open"),
        "high": _pick(row, "dayHigh", "high"),
        "low": _pick(row, "dayLow", "low"),
        "close": round(close, 4),
        "volume": int(_pick(row, "volume") or 0) or None,
        "change_pct": round(change_pct / 100.0, 6) if change_pct is not None else None,
        "change_5d_pct": None,
        "change_20d_pct": None,
        "avg_volume_10d": None,
        "avg_volume_30d": int(avg_volume) if avg_volume else None,
        "is_penny": close < 5.0,
        "is_micro": close < 50.0,
    }


def fetch_fmp_market_caps(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Market cap + shares outstanding, harvested from the same batch-quote call."""
    key = api_key()
    results: Dict[str, Dict[str, Any]] = {}
    if not key or not tickers:
        return results

    with httpx.Client(timeout=30) as client:
        for batch in _batches([t.upper() for t in tickers], QUOTE_BATCH):
            try:
                resp = client.get(QUOTE_URL, params={"symbols": ",".join(batch), "apikey": key})
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                if not isinstance(payload, list):
                    continue
                for row in payload:
                    symbol = (row.get("symbol") or "").upper().strip()
                    mcap = _pick(row, "marketCap", "marketCapitalization")
                    if not symbol or not mcap:
                        continue
                    results[symbol] = {
                        "market_cap": mcap,
                        "shares_outstanding": _pick(row, "sharesOutstanding"),
                        "company_name": row.get("name"),
                    }
            except Exception as e:
                logger.debug(f"FMP market cap batch failed: {e}")
            time.sleep(PACE_S)

    logger.info(f"FMP market caps: {len(results)}/{len(tickers)} tickers")
    return results


def fetch_fmp_float(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Float shares per ticker — the input lens 4 has never actually had.

    One call per symbol, so `tickers` should be passed in priority order and is
    capped by FMP_FLOAT_BUDGET.
    """
    key = api_key()
    results: Dict[str, Dict[str, Any]] = {}
    if not key or not tickers:
        return results

    todo = [t.upper() for t in tickers][:float_budget()]
    logger.info(f"FMP float: fetching {len(todo)} tickers")

    errors = 0
    with httpx.Client(timeout=30) as client:
        for ticker in todo:
            try:
                resp = client.get(FLOAT_URL, params={"symbol": ticker, "apikey": key})
                if resp.status_code == 429:
                    logger.warning("FMP 429 — sleeping 20s")
                    time.sleep(20)
                    continue
                if resp.status_code != 200:
                    errors += 1
                    continue
                payload = resp.json()
                row = payload[0] if isinstance(payload, list) and payload else payload
                if not isinstance(row, dict):
                    continue
                # Only a genuine share count counts as float. FMP's `freeFloat`
                # is a percentage, and shares outstanding is a different number
                # entirely — a tightly-held micro-cap's whole edge is that its
                # float is far smaller. A wrong float is worse than none.
                float_shares = _pick(row, "floatShares")
                shares_out = _pick(row, "outstandingShares", "sharesOutstanding")
                if not float_shares:
                    continue
                results[ticker] = {
                    "float_shares": float_shares,
                    "shares_outstanding": shares_out,
                }
            except Exception as e:
                errors += 1
                logger.debug(f"FMP float failed for {ticker}: {e}")
            time.sleep(PACE_S)

    logger.info(f"FMP float: {len(results)}/{len(todo)} tickers ({errors} errors)")
    return results
