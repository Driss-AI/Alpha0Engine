"""
Price Fetcher
=============
Pulls daily OHLCV data via yfinance (free, no API key).
Computes market cap, average volumes, and change metrics.

yfinance constraints:
  - No official rate limit, but aggressive calls get throttled
  - Batch downloads are efficient (up to ~500 tickers at once)
  - Market cap and shares outstanding come from .info (slower, per-ticker)
  - Data delayed ~15-20 min during market hours
"""
import logging
from typing import Dict, Any, List

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # tickers per yfinance download call


def fetch_batch_prices(
    tickers: List[str],
    period: str = "35d",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Batch-fetch daily OHLCV for a list of tickers.
    Returns {ticker: [day_records]} sorted oldest→newest.
    """
    if not tickers:
        return {}

    results = {}

    # Process in batches to avoid yfinance choking
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        batch_str = " ".join(batch)
        logger.info(f"Fetching prices for {len(batch)} tickers (batch {i // BATCH_SIZE + 1})")

        try:
            df = yf.download(
                batch_str,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

            if df.empty:
                logger.warning(f"Empty result for batch starting at {i}")
                continue

            # Single ticker returns flat columns, multi returns MultiIndex
            if len(batch) == 1:
                ticker = batch[0]
                records = _parse_single_ticker_df(ticker, df)
                if records:
                    results[ticker] = records
            else:
                for ticker in batch:
                    try:
                        if ticker in df.columns.get_level_values(0):
                            ticker_df = df[ticker].dropna(how="all")
                            records = _parse_single_ticker_df(ticker, ticker_df)
                            if records:
                                results[ticker] = records
                    except (KeyError, TypeError) as e:
                        logger.debug(f"No data for {ticker}: {e}")

        except Exception as e:
            logger.error(f"yfinance batch download failed: {e}")

    return results


def _parse_single_ticker_df(ticker: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Parse a single-ticker DataFrame into day records."""
    records = []
    df = df.dropna(subset=["Close"])

    if df.empty:
        return records

    closes = df["Close"].tolist()

    for idx, (dt, row) in enumerate(df.iterrows()):
        trade_dt = dt.date() if hasattr(dt, "date") else dt

        close = float(row["Close"]) if pd.notna(row.get("Close")) else None
        if close is None or close <= 0:
            continue

        # Daily change
        change_pct = None
        if idx > 0 and closes[idx - 1] > 0:
            change_pct = round((close - closes[idx - 1]) / closes[idx - 1], 6)

        # 5-day change
        change_5d = None
        if idx >= 5 and closes[idx - 5] > 0:
            change_5d = round((close - closes[idx - 5]) / closes[idx - 5], 6)

        # 20-day change
        change_20d = None
        if idx >= 20 and closes[idx - 20] > 0:
            change_20d = round((close - closes[idx - 20]) / closes[idx - 20], 6)

        # Rolling average volumes
        volumes = df["Volume"].tolist()
        avg_vol_10d = None
        avg_vol_30d = None
        if idx >= 9:
            recent_vols = [v for v in volumes[idx - 9:idx + 1] if pd.notna(v)]
            if recent_vols:
                avg_vol_10d = round(sum(recent_vols) / len(recent_vols), 0)
        if idx >= 29:
            recent_vols = [v for v in volumes[idx - 29:idx + 1] if pd.notna(v)]
            if recent_vols:
                avg_vol_30d = round(sum(recent_vols) / len(recent_vols), 0)

        records.append({
            "ticker": ticker,
            "trade_date": trade_dt,
            "open": round(float(row["Open"]), 4) if pd.notna(row.get("Open")) else None,
            "high": round(float(row["High"]), 4) if pd.notna(row.get("High")) else None,
            "low": round(float(row["Low"]), 4) if pd.notna(row.get("Low")) else None,
            "close": round(close, 4),
            "volume": float(row["Volume"]) if pd.notna(row.get("Volume")) else None,
            "change_pct": change_pct,
            "change_5d_pct": change_5d,
            "change_20d_pct": change_20d,
            "avg_volume_10d": avg_vol_10d,
            "avg_volume_30d": avg_vol_30d,
            "is_penny": close < 5.0,
            "is_micro": close < 50.0,
        })

    return records


def fetch_market_caps(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch market cap and shares outstanding for a batch of tickers.
    Uses yfinance .info (slower — one call per ticker).
    Returns {ticker: {market_cap, shares_outstanding}}.
    """
    import time
    results = {}

    for i, ticker in enumerate(tickers):
        try:
            info = yf.Ticker(ticker).info
            mcap = info.get("marketCap")
            shares = info.get("sharesOutstanding")

            if mcap or shares:
                results[ticker] = {
                    "market_cap": mcap,
                    "shares_outstanding": shares,
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "company_name": info.get("shortName") or info.get("longName"),
                    # Short interest data (Lens 4: Float Mechanics)
                    "shares_short": info.get("sharesShort"),
                    "short_pct_float": info.get("shortPercentOfFloat"),
                    "short_ratio": info.get("shortRatio"),  # days to cover
                    "float_shares": info.get("floatShares"),
                }
            # Rate limit: 1 req/sec to avoid Yahoo 429s
            time.sleep(1.0)
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                logger.warning(f"Rate limited at ticker {ticker}, sleeping 30s...")
                time.sleep(30)
            else:
                logger.debug(f"Info fetch failed for {ticker}: {e}")

    return results


def fetch_universe_tickers_sec() -> List[Dict[str, str]]:
    """
    Pull the full SEC EDGAR ticker→CIK mapping.
    This is the canonical list of every public company.
    Free, no API key. ~13,000 entries.
    """
    import httpx

    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": "Alpha0Engine contact@alpha0engine.com"}

    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.error(f"SEC tickers fetch returned {resp.status_code}")
            return []

        data = resp.json()
        tickers = []
        for entry in data.values():
            tickers.append({
                "cik": str(entry.get("cik_str", "")),
                "ticker": entry.get("ticker", ""),
                "company_name": entry.get("title", ""),
            })
        logger.info(f"Loaded {len(tickers)} tickers from SEC EDGAR")
        return tickers

    except Exception as e:
        logger.error(f"SEC tickers fetch failed: {e}")
        return []
