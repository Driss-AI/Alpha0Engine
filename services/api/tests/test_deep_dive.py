import pytest
from datetime import date
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.entities import Entity
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.ticker_timeline import TickerTimeline
from shared.schemas.signals import Signal


async def _seed_entity(session: AsyncSession, ticker: str = "ACME", cik: str = "0001234") -> Entity:
    entity = Entity(
        id="ent-1", name="Acme Corp", ticker=ticker, cik=cik,
        entity_type="public", sector="tech",
    )
    session.add(entity)
    await session.commit()
    await session.refresh(entity)
    return entity


async def _seed_screen(session: AsyncSession, entity: Entity) -> EquityScreen:
    screen = EquityScreen(
        entity_id=entity.id, ticker=entity.ticker, company_name=entity.name,
        composite_score=0.75, conviction_tier="HIGH", active_lenses=3,
        catalyst_score=0.8, earnings_score=0.6, demand_score=0.7,
        float_score=0.5, smart_money_score=0.4,
    )
    session.add(screen)
    await session.commit()
    return screen


@pytest.mark.asyncio
async def test_timeline_empty(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/ACME/timeline")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_timeline_with_events(client: AsyncClient, session: AsyncSession):
    event = TickerTimeline(
        ticker="ACME", event_type="filing", event_title="10-K",
        event_date=date.today(), event_data={},
    )
    session.add(event)
    await session.commit()

    resp = await client.get("/api/v1/1000x/ACME/timeline")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["event_type"] == "filing"


@pytest.mark.asyncio
async def test_signals_no_entity(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/FAKE/signals")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_signals_with_entity(client: AsyncClient, session: AsyncSession):
    entity = await _seed_entity(session)
    signal = Signal(
        entity_id=entity.id, signal_type="insider_buy",
        signal_date=date.today(), source="edgar_form4",
    )
    session.add(signal)
    await session.commit()

    resp = await client.get("/api/v1/1000x/ACME/signals")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_filings_no_entity(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/FAKE/filings")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_filings_with_entity(client: AsyncClient, session: AsyncSession):
    entity = await _seed_entity(session)
    signal = Signal(
        entity_id=entity.id, signal_type="8k_filing",
        signal_date=date.today(), source="edgar_8k",
        raw_data={"form": "8-K", "url": "https://sec.gov/test"},
    )
    session.add(signal)
    await session.commit()

    resp = await client.get("/api/v1/1000x/ACME/filings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "ACME"
    assert len(data["filings"]) == 1


@pytest.mark.asyncio
async def test_eps_chart_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/FAKE/eps-chart")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eps_chart_found(client: AsyncClient, session: AsyncSession):
    entity = await _seed_entity(session)
    await _seed_screen(session, entity)

    resp = await client.get("/api/v1/1000x/ACME/eps-chart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "ACME"
    assert "eps_trajectory" in data


@pytest.mark.asyncio
async def test_research_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/1000x/FAKE/research")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_research_found(client: AsyncClient, session: AsyncSession):
    entity = await _seed_entity(session)
    await _seed_screen(session, entity)

    resp = await client.get("/api/v1/1000x/ACME/research")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "ACME"
    assert data["lens_scorecard"] is not None
    assert data["lens_scorecard"]["conviction_tier"] == "HIGH"
