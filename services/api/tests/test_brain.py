import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.brain_opportunity import BrainOpportunity
from shared.schemas.brain_narrative import BrainNarrative


async def _seed_opportunity(
    session: AsyncSession,
    ticker: str = "ACME",
    conviction: str = "HIGH",
    status: str = "active",
    confidence: float = 0.85,
    return_pct: float | None = None,
) -> BrainOpportunity:
    opp = BrainOpportunity(
        entity_id=f"ent-{ticker.lower()}",
        ticker=ticker,
        company_name=f"{ticker} Inc",
        thesis=f"Strong thesis for {ticker}",
        narrative=f"Full narrative for {ticker} with evidence",
        conviction=conviction,
        confidence_score=confidence,
        status=status,
        return_pct=return_pct,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(opp)
    await session.commit()
    await session.refresh(opp)
    return opp


async def _seed_narrative(
    session: AsyncSession,
    ticker: str = "ACME",
    version: int = 1,
) -> BrainNarrative:
    narr = BrainNarrative(
        entity_id=f"ent-{ticker.lower()}",
        ticker=ticker,
        company_name=f"{ticker} Inc",
        narrative_text=f"AI analysis for {ticker}",
        summary=f"Short summary for {ticker}",
        conviction_level="BUY",
        version=version,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(narr)
    await session.commit()
    await session.refresh(narr)
    return narr


@pytest.mark.asyncio
async def test_picks_empty(client: AsyncClient):
    resp = await client.get("/api/v1/brain/picks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_picks_returns_seeded(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME")
    await _seed_opportunity(session, "TSLA", conviction="LOW", confidence=0.5)

    resp = await client.get("/api/v1/brain/picks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["confidence_score"] >= data[1]["confidence_score"]


@pytest.mark.asyncio
async def test_picks_filter_conviction(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", conviction="HIGH")
    await _seed_opportunity(session, "TSLA", conviction="LOW")

    resp = await client.get("/api/v1/brain/picks", params={"conviction": "HIGH"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "ACME"


@pytest.mark.asyncio
async def test_picks_filter_status(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", status="active")
    await _seed_opportunity(session, "TSLA", status="expired")

    resp = await client.get("/api/v1/brain/picks", params={"status": "expired"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "TSLA"


@pytest.mark.asyncio
async def test_picks_status_all(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", status="active")
    await _seed_opportunity(session, "TSLA", status="expired")

    resp = await client.get("/api/v1/brain/picks", params={"status": "all"})
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_pick_by_id(client: AsyncClient, session: AsyncSession):
    opp = await _seed_opportunity(session, "ACME")
    resp = await client.get(f"/api/v1/brain/picks/{opp.id}")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "ACME"
    assert resp.json()["thesis"] == "Strong thesis for ACME"


@pytest.mark.asyncio
async def test_pick_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/brain/picks/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_narrative(client: AsyncClient, session: AsyncSession):
    await _seed_narrative(session, "ACME", version=1)
    await _seed_narrative(session, "ACME", version=2)

    resp = await client.get("/api/v1/brain/ACME/narrative")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "ACME"
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_narrative_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/brain/FAKE/narrative")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ticker_history(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", conviction="HIGH")
    await _seed_opportunity(session, "ACME", conviction="MEDIUM")
    await _seed_opportunity(session, "TSLA")

    resp = await client.get("/api/v1/brain/ACME/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(item["ticker"] == "ACME" for item in data)


@pytest.mark.asyncio
async def test_stats(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", conviction="HIGH")
    await _seed_opportunity(session, "TSLA", conviction="LOW")

    resp = await client.get("/api/v1/brain/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_opportunities"] == 2
    assert data["by_conviction"]["HIGH"] == 1
    assert data["by_conviction"]["LOW"] == 1
    assert data["avg_confidence_score"] > 0


@pytest.mark.asyncio
async def test_stats_empty(client: AsyncClient):
    resp = await client.get("/api/v1/brain/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_opportunities"] == 0


@pytest.mark.asyncio
async def test_feedback_stats(client: AsyncClient, session: AsyncSession):
    await _seed_opportunity(session, "ACME", status="hit", return_pct=45.0, conviction="HIGH")
    await _seed_opportunity(session, "TSLA", status="miss", return_pct=-15.0, conviction="LOW")

    resp = await client.get("/api/v1/brain/feedback/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_resolved"] == 2
    assert data["hits"] == 1
    assert data["misses"] == 1
    assert data["hit_rate"] == 50.0
    assert data["avg_return"] == 15.0
    assert data["by_conviction"]["HIGH"]["total"] == 1


@pytest.mark.asyncio
async def test_feedback_stats_empty(client: AsyncClient):
    resp = await client.get("/api/v1/brain/feedback/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_resolved"] == 0
    assert data["hit_rate"] == 0
