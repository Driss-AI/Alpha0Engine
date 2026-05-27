import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_watchlist_item(client: AsyncClient):
    resp = await client.post("/api/v1/watchlist", json={
        "ticker": "aapl",
        "priority": "high",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["priority"] == "high"
    assert data["hearted"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_add_duplicate_re_hearts(client: AsyncClient):
    await client.post("/api/v1/watchlist", json={"ticker": "tsla"})
    resp = await client.post("/api/v1/watchlist", json={"ticker": "tsla", "notes": "updated"})
    assert resp.status_code == 201
    assert resp.json()["notes"] == "updated"
    assert resp.json()["hearted"] is True


@pytest.mark.asyncio
async def test_invalid_priority(client: AsyncClient):
    resp = await client.post("/api/v1/watchlist", json={
        "ticker": "msft",
        "priority": "ultra",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_watchlist(client: AsyncClient):
    await client.post("/api/v1/watchlist", json={"ticker": "aapl"})
    await client.post("/api/v1/watchlist", json={"ticker": "goog"})
    resp = await client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_filter_priority(client: AsyncClient):
    await client.post("/api/v1/watchlist", json={"ticker": "aapl", "priority": "high"})
    await client.post("/api/v1/watchlist", json={"ticker": "goog", "priority": "low"})
    resp = await client.get("/api/v1/watchlist", params={"priority": "high"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_update_watchlist_item(client: AsyncClient):
    create = await client.post("/api/v1/watchlist", json={"ticker": "aapl"})
    item_id = create.json()["id"]
    resp = await client.patch(f"/api/v1/watchlist/{item_id}", json={"notes": "buy the dip"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "buy the dip"


@pytest.mark.asyncio
async def test_update_nonexistent(client: AsyncClient):
    resp = await client.patch("/api/v1/watchlist/fake-id", json={"notes": "nope"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_watchlist_item(client: AsyncClient):
    create = await client.post("/api/v1/watchlist", json={"ticker": "aapl"})
    item_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/watchlist/{item_id}")
    assert resp.status_code == 204
    listing = await client.get("/api/v1/watchlist")
    assert len(listing.json()) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent(client: AsyncClient):
    resp = await client.delete("/api/v1/watchlist/fake-id")
    assert resp.status_code == 404
