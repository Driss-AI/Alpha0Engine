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
  - /stable/batch-quote   → price, VOLUME, marketCap (100/call). Note that the
    documented response carries no avgVolume and no sharesOutstanding; both are
    still read tolerantly for the endpoints that do return them.
  - /stable/shares-float  → float shares + shares outstanding

/stable/batch-quote is not included in every FMP plan — a key without it gets
402 on every call. That is reported once and the phase stops; the Stooq/Finnhub
chain below carries the run.

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

# A 429 is either a per-minute burst (worth waiting out) or a spent daily quota
# (never recovers within a run). Retrying a bounded number of times handles the
# first; abandoning the phase after that handles the second. The alternative —
# sleeping per ticker — costs 20s × the whole float list, which is how a run
# once spent 90 minutes in this module and was killed at the pipeline timeout.
RATE_LIMIT_SLEEP_S = 5.0    # first back-off, doubled on each retry
MAX_RATE_LIMIT_RETRIES = 3  # consecutive 429s on one call before giving up

# Nothing about these improves by asking again with the same key: the plan does
# not include the endpoint, or the key is rejected. Stop the phase on the first
# one rather than repeating it once per batch.
TERMINAL_STATUSES = frozenset({401, 402, 403})


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


def _message(resp: "httpx.Response") -> str:
    """FMP's own explanation, which is the only thing worth logging."""
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            for k in ("Error Message", "error", "message"):
                if payload.get(k):
                    return str(payload[k])[:200]
    except Exception:
        pass
    return resp.text[:200]


class _Phase:
    """Per-phase call bookkeeping.

    `aborted` carries the reason FMP gave for stopping, so the caller can log
    once, in full, at a level that survives LOG_LEVEL=INFO. The failure this
    replaced logged its body at DEBUG, which meant a production run could emit
    91 identical rejections without ever naming one.
    """

    def __init__(self, name: str):
        self.name = name
        self.errors = 0
        self.aborted: Optional[str] = None
        self._logged_error = False

    def note_error(self, detail: str) -> None:
        self.errors += 1
        if not self._logged_error:
            self._logged_error = True
            logger.warning(f"FMP {self.name}: {detail}")
        else:
            logger.debug(f"FMP {self.name}: {detail}")


def _get(client: "httpx.Client", url: str, params: Dict[str, Any],
         phase: _Phase) -> Optional[Any]:
    """One GET with bounded back-off; None when it produced no usable body.

    Sets `phase.aborted` when FMP signals something that will not resolve
    inside this run, so the caller stops calling instead of repeating it once
    per ticker.
    """
    delay = RATE_LIMIT_SLEEP_S
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            resp = client.get(url, params=params)
        except Exception as e:
            phase.note_error(f"request failed: {e}")
            return None
        # Pace here rather than in the callers: a `continue` past a courtesy
        # sleep is how the old loops ended up firing batches back to back.
        time.sleep(PACE_S)

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                phase.note_error(f"non-JSON body: {resp.text[:200]}")
                return None

        if resp.status_code == 429:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                phase.aborted = (
                    f"rate limited after {MAX_RATE_LIMIT_RETRIES} retries "
                    f"— {_message(resp)}"
                )
                return None
            logger.warning(
                f"FMP 429 on {phase.name} — retry "
                f"{attempt + 1}/{MAX_RATE_LIMIT_RETRIES} in {delay:.0f}s"
            )
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code in TERMINAL_STATUSES:
            phase.aborted = f"HTTP {resp.status_code} — {_message(resp)}"
            return None

        phase.note_error(f"HTTP {resp.status_code}: {_message(resp)}")
        return None

    return None


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
    phase = _Phase("batch-quote")
    batches = list(_batches([t.upper() for t in tickers], QUOTE_BATCH))
    logger.info(f"FMP quotes: {len(tickers)} tickers in {len(batches)} batched calls")

    with httpx.Client(timeout=30) as client:
        for batch in batches:
            payload = _get(client, QUOTE_URL,
                           {"symbols": ",".join(batch), "apikey": key}, phase)
            if phase.aborted:
                break
            if payload is None:
                continue
            if not isinstance(payload, list):
                phase.note_error(f"unexpected payload: {str(payload)[:200]}")
                continue
            for row in payload:
                rec = _quote_record(row, today)
                if rec:
                    results[rec["ticker"]] = [rec]

    if phase.aborted:
        logger.warning(
            f"FMP quotes: abandoned after {phase.aborted}. "
            f"Falling back to Yahoo/Stooq/Finnhub for the remaining tickers."
        )
    logger.info(
        f"FMP quotes: {len(results)}/{len(tickers)} tickers ({phase.errors} errors)"
    )
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

    phase = _Phase("batch-quote (market caps)")
    with httpx.Client(timeout=30) as client:
        for batch in _batches([t.upper() for t in tickers], QUOTE_BATCH):
            payload = _get(client, QUOTE_URL,
                           {"symbols": ",".join(batch), "apikey": key}, phase)
            if phase.aborted:
                break
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

    if phase.aborted:
        logger.warning(f"FMP market caps: abandoned after {phase.aborted}")
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

    phase = _Phase("shares-float")
    attempted = 0
    with httpx.Client(timeout=30) as client:
        for ticker in todo:
            payload = _get(client, FLOAT_URL,
                           {"symbol": ticker, "apikey": key}, phase)
            if phase.aborted:
                break
            attempted += 1
            if payload is None:
                continue
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

    if phase.aborted:
        logger.warning(
            f"FMP float: abandoned after {attempted}/{len(todo)} tickers "
            f"— {phase.aborted}. Lens 4 runs on whatever float the other "
            f"sources supplied."
        )
    logger.info(
        f"FMP float: {len(results)}/{len(todo)} tickers ({phase.errors} errors)"
    )
    return results
