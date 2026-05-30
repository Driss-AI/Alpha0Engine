"""Tests for the alerts router + outcome population (Sprint 10.3)."""
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.alert import Alert
from shared.schemas.daily_prices import DailyPrice
from shared.services.alert_outcomes import forward_return, max_drawdown, populate_alert_returns


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── outcome math (pure) ─────────────────────────────────────────────────────

def test_forward_return():
    assert forward_return(100, 150) == 0.5
    assert forward_return(100, 80) == -0.2
    assert forward_return(None, 100) is None
    assert forward_return(0, 100) is None


def test_max_drawdown():
    assert max_drawdown([100, 120, 90, 110]) == round((90 - 120) / 120, 4)
    assert max_drawdown([100, 110, 120]) == 0.0   # monotonic up
    assert max_drawdown([]) is None


# ── alerts router ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alerts_today_empty(client: AsyncClient):
    resp = await client.get("/api/v1/alerts/today")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_list_and_filter_alerts(client: AsyncClient, session: AsyncSession):
    session.add_all([
        Alert(ticker="BE", lane_id="L1_AI_INFRA", bucket="SETUP_READY", composite_score=0.8,
              opportunity_score=88, delivered=True),
        Alert(ticker="SPRB", lane_id="L2_BIOTECH", bucket="DEEP_DIVE", composite_score=0.7,
              opportunity_score=70, delivered=True),
    ])
    await session.commit()

    # all
    resp = await client.get("/api/v1/alerts")
    assert resp.json()["count"] == 2
    # filter by lane
    resp = await client.get("/api/v1/alerts", params={"lane": "L2_BIOTECH"})
    assert resp.json()["count"] == 1
    assert resp.json()["alerts"][0]["ticker"] == "SPRB"
    # filter by bucket
    resp = await client.get("/api/v1/alerts", params={"bucket": "SETUP_READY"})
    assert resp.json()["count"] == 1


@pytest.mark.asyncio
async def test_record_outcome(client: AsyncClient, session: AsyncSession):
    a = Alert(ticker="BE", lane_id="L1_AI_INFRA", bucket="SETUP_READY", composite_score=0.8)
    session.add(a)
    await session.commit()
    alert_id = a.id

    resp = await client.post(f"/api/v1/alerts/{alert_id}/outcome",
                             json={"my_action": "dove", "outcome_notes": "took a starter position",
                                   "was_tradable": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["my_action"] == "dove"
    assert body["was_tradable"] is True


@pytest.mark.asyncio
async def test_record_outcome_rejects_bad_action(client: AsyncClient, session: AsyncSession):
    a = Alert(ticker="X", bucket="DEEP_DIVE")
    session.add(a)
    await session.commit()
    resp = await client.post(f"/api/v1/alerts/{a.id}/outcome", json={"my_action": "yolo"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_record_outcome_404(client: AsyncClient):
    resp = await client.post("/api/v1/alerts/nope/outcome", json={"my_action": "watched"})
    assert resp.status_code == 404


# ── forward-return population from prices ────────────────────────────────────

@pytest.mark.asyncio
async def test_populate_alert_returns(session: AsyncSession):
    sent = date(2026, 1, 1)
    a = Alert(ticker="BE", lane_id="L1_AI_INFRA", bucket="SETUP_READY",
              sent_at=datetime(2026, 1, 1))
    session.add(a)
    # base price ~100 at alert; +20% by day 30
    session.add_all([
        DailyPrice(ticker="BE", trade_date=sent, close=100.0),
        DailyPrice(ticker="BE", trade_date=sent + timedelta(days=7), close=110.0),
        DailyPrice(ticker="BE", trade_date=sent + timedelta(days=30), close=120.0),
    ])
    await session.commit()

    updated = await populate_alert_returns(session, as_of=date(2026, 3, 1))
    assert updated == 1
    from sqlmodel import select
    refreshed = (await session.exec(select(Alert).where(Alert.ticker == "BE"))).first()
    assert refreshed.forward_return_7d == 0.1
    assert refreshed.forward_return_30d == 0.2
