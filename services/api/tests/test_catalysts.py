import pytest
from datetime import date, timedelta
from httpx import AsyncClient


def _future_date(days: int = 10) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_pin_catalyst(client: AsyncClient):
    resp = await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "fda",
        "title": "Phase 3 readout",
        "expected_date": _future_date(),
        "status": "upcoming",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "MRNA"
    assert data["user_pinned"] is True
    assert data["catalyst_type"] == "fda"


@pytest.mark.asyncio
async def test_pin_invalid_type(client: AsyncClient):
    resp = await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "bogus",
        "title": "test",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pin_invalid_status(client: AsyncClient):
    resp = await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "fda",
        "title": "test",
        "status": "bogus",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_catalysts(client: AsyncClient):
    await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "fda",
        "title": "Phase 3",
        "status": "upcoming",
    })
    await client.post("/api/v1/catalysts/pin", json={
        "ticker": "nvda",
        "catalyst_type": "earnings",
        "title": "Q4 earnings",
        "status": "upcoming",
    })
    resp = await client.get("/api/v1/catalysts")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_catalysts_filter_ticker(client: AsyncClient):
    await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna", "catalyst_type": "fda", "title": "t1", "status": "upcoming",
    })
    await client.post("/api/v1/catalysts/pin", json={
        "ticker": "nvda", "catalyst_type": "earnings", "title": "t2", "status": "upcoming",
    })
    resp = await client.get("/api/v1/catalysts", params={"ticker": "mrna"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["ticker"] == "MRNA"


@pytest.mark.asyncio
async def test_calendar_returns_future_events(client: AsyncClient):
    await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "fda",
        "title": "future event",
        "expected_date": _future_date(15),
        "status": "upcoming",
    })
    resp = await client.get("/api/v1/catalysts/calendar", params={"range": "30d"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_calendar_bad_range(client: AsyncClient):
    resp = await client.get("/api/v1/catalysts/calendar", params={"range": "abc"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_catalyst(client: AsyncClient):
    create = await client.post("/api/v1/catalysts/pin", json={
        "ticker": "mrna",
        "catalyst_type": "fda",
        "title": "Phase 3",
        "status": "upcoming",
    })
    eid = create.json()["id"]
    resp = await client.patch(f"/api/v1/catalysts/{eid}", json={"status": "confirmed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_update_nonexistent(client: AsyncClient):
    resp = await client.patch("/api/v1/catalysts/fake-id", json={"title": "nope"})
    assert resp.status_code == 404
