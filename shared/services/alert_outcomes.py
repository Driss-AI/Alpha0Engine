"""
Alert outcome population (Sprint 10.3) — pure return math + DB updater.

Reads DailyPrice and fills forward_return_7d/30d/90d + max_drawdown on each Alert
whose horizon has elapsed. Called by the daily pipeline / alert-engine.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

HORIZONS = {"forward_return_7d": 7, "forward_return_30d": 30, "forward_return_90d": 90}


def forward_return(base_price: Optional[float], later_price: Optional[float]) -> Optional[float]:
    """Simple return fraction (0.25 = +25%). None if either price missing/zero."""
    if not base_price or not later_price or base_price <= 0:
        return None
    return round((later_price - base_price) / base_price, 4)


def max_drawdown(prices: list[float]) -> Optional[float]:
    """Largest peak-to-trough drop across an ordered price series (negative fraction)."""
    if not prices:
        return None
    peak = prices[0]
    mdd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            dd = (p - peak) / peak
            if dd < mdd:
                mdd = dd
    return round(mdd, 4)


async def populate_alert_returns(session, *, as_of: Optional[date] = None) -> int:
    """Fill forward returns + drawdown for alerts whose horizons have elapsed.

    Returns the number of alerts updated. Idempotent — only fills None fields.
    """
    from sqlalchemy import select
    from shared.schemas.alert import Alert
    from shared.schemas.daily_prices import DailyPrice

    today = as_of or date.today()
    updated = 0

    alerts = (await session.execute(select(Alert))).scalars().all()
    for a in alerts:
        sent_day = a.sent_at.date() if a.sent_at else None
        if not sent_day:
            continue

        # Base price = close on/just after the alert date.
        base_rows = (await session.execute(
            select(DailyPrice).where(
                DailyPrice.ticker == a.ticker,
                DailyPrice.trade_date >= sent_day,
                DailyPrice.trade_date <= sent_day + timedelta(days=5),
            ).order_by(DailyPrice.trade_date)
        )).scalars().all()
        if not base_rows:
            continue
        base_price = base_rows[0].close
        changed = False

        for field, horizon in HORIZONS.items():
            if getattr(a, field) is not None:
                continue
            target = sent_day + timedelta(days=horizon)
            if target > today:
                continue
            later_rows = (await session.execute(
                select(DailyPrice).where(
                    DailyPrice.ticker == a.ticker,
                    DailyPrice.trade_date >= target - timedelta(days=5),
                    DailyPrice.trade_date <= target + timedelta(days=5),
                ).order_by(DailyPrice.trade_date)
            )).scalars().all()
            if later_rows:
                ret = forward_return(base_price, later_rows[len(later_rows) // 2].close)
                if ret is not None:
                    setattr(a, field, ret)
                    changed = True

        # Max drawdown over the window observed so far (up to 90d).
        if a.max_drawdown is None:
            window = (await session.execute(
                select(DailyPrice).where(
                    DailyPrice.ticker == a.ticker,
                    DailyPrice.trade_date >= sent_day,
                    DailyPrice.trade_date <= sent_day + timedelta(days=90),
                ).order_by(DailyPrice.trade_date)
            )).scalars().all()
            closes = [r.close for r in window if r.close]
            if len(closes) >= 2:
                a.max_drawdown = max_drawdown(closes)
                changed = True

        if changed:
            session.add(a)
            updated += 1

    await session.commit()
    return updated
