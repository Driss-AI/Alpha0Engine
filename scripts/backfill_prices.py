#!/usr/bin/env python3
"""
Historical price backfill (Sprint 10 follow-up)

`ingest-prices` only stores ~35 days of OHLCV, so the seeded historical backtest
cases (2023–2024 dates) have no `DailyPrice` rows to join against. This script
backfills multi-year daily history (via yfinance) for a set of tickers so
`backtest_dataset.py` can actually compute forward returns.

By default it backfills the tickers in `seed_known_cases.py`; pass --tickers to
override. Idempotent (upserts on ticker+trade_date).

Usage:
    python scripts/backfill_prices.py                     # seed tickers, 5y
    python scripts/backfill_prices.py --period 3y
    python scripts/backfill_prices.py --tickers BE,VST,SPRB
    python scripts/backfill_prices.py --dry-run

Requires DATABASE_URL + yfinance.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


def _seed_tickers() -> list[str]:
    path = os.path.join(os.path.dirname(__file__), "seed_known_cases.py")
    spec = importlib.util.spec_from_file_location("seed_known_cases", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules["seed_known_cases"] = m
    spec.loader.exec_module(m)
    return sorted({c.ticker for c in m.ALL_CASES})


def fetch_history(ticker: str, period: str) -> list[dict]:
    """Fetch daily OHLCV history. Returns [{trade_date, open, high, low, close, volume}]."""
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    out: list[dict] = []
    try:
        hist = yf.Ticker(ticker).history(period=period)
        for ts, row in hist.iterrows():
            out.append({
                "trade_date": ts.date(),
                "open": float(row["Open"]) if row["Open"] == row["Open"] else None,
                "high": float(row["High"]) if row["High"] == row["High"] else None,
                "low": float(row["Low"]) if row["Low"] == row["Low"] else None,
                "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
            })
    except Exception as e:
        print(f"  {ticker}: fetch failed — {e}")
    return out


async def backfill(tickers: list[str], period: str, dry_run: bool) -> int:
    from sqlalchemy import select
    from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
    from shared.schemas.daily_prices import DailyPrice

    if not dry_run:
        await create_db_and_tables()

    total = 0
    for ticker in tickers:
        rows = fetch_history(ticker, period)
        print(f"  {ticker:6s}: {len(rows)} daily bars")
        if dry_run or not rows:
            total += len(rows)
            continue
        async with AsyncSessionLocal() as session:
            for r in rows:
                existing = (await session.execute(
                    select(DailyPrice).where(
                        DailyPrice.ticker == ticker,
                        DailyPrice.trade_date == r["trade_date"],
                    )
                )).scalar_one_or_none()
                if existing:
                    if existing.close is None and r["close"] is not None:
                        existing.close = r["close"]
                        existing.volume = r["volume"]
                        session.add(existing)
                    continue
                session.add(DailyPrice(
                    ticker=ticker, trade_date=r["trade_date"],
                    open=r["open"], high=r["high"], low=r["low"],
                    close=r["close"], volume=r["volume"],
                ))
                total += 1
            await session.commit()
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tickers", help="Comma-separated tickers (default: seed_known_cases tickers)")
    p.add_argument("--period", default="5y", help="yfinance period (default 5y to cover 2023+ seeds)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else _seed_tickers()
    print(f"\nBackfilling {len(tickers)} tickers, period={args.period}"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")
    written = asyncio.run(backfill(tickers, args.period, args.dry_run))
    print(f"\n{'Would write' if args.dry_run else 'Wrote'} ~{written} DailyPrice rows.")
    print("Next: python scripts/backtest_dataset.py && "
          "python scripts/backtest_analyze.py --lane L1_AI_INFRA --output reports/backtest_L1.md")


if __name__ == "__main__":
    main()
