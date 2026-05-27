import pytest
from datetime import date
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.score_snapshot import ScoreSnapshot
from shared.schemas.equity_screen import EquityScreen


async def _seed_snapshot(session: AsyncSession, ticker: str, score: float, snap_date: date):
    snap = ScoreSnapshot(
        ticker=ticker, composite_score=score, snapshot_date=snap_date,
        conviction_tier="WATCH",
    )
    session.add(snap)
    await session.commit()


async def _seed_screen(session: AsyncSession, ticker: str, score: float):
    screen = EquityScreen(
        entity_id=f"ent-{ticker.lower()}",
        ticker=ticker, company_name=f"{ticker} Inc",
        composite_score=score, conviction_tier="WATCH", active_lenses=2,
    )
    session.add(screen)
    await session.commit()


@pytest.mark.asyncio
async def test_deltas_empty(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/deltas")
    assert resp.status_code == 200
    data = resp.json()
    assert data["movers"] == []
    assert data["new_entries"] == []


@pytest.mark.asyncio
async def test_movers_empty(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/movers")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_new_entries_empty(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/new-entries")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_write_snapshots(client: AsyncClient, session: AsyncSession):
    await _seed_screen(session, "ACME", 0.8)
    resp = await client.post("/api/v1/1000x/snapshots/write")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["snapshots_written"] >= 1


@pytest.mark.asyncio
async def test_movers_direction(client: AsyncClient):
    resp_up = await client.get("/api/v1/1000x/movers", params={"direction": "up"})
    assert resp_up.status_code == 200
    resp_down = await client.get("/api/v1/1000x/movers", params={"direction": "down"})
    assert resp_down.status_code == 200


@pytest.mark.asyncio
async def test_movers_invalid_direction(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/movers", params={"direction": "sideways"})
    assert resp.status_code == 422
