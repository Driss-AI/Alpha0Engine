"""Tests for GET /api/v1/data-freshness (Sprint 6.4)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.data_freshness import DataFreshness


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_empty_table_returns_empty_list(client: AsyncClient):
    resp = await client.get("/api/v1/data-freshness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == []
    assert data["summary"] == {"fresh": 0, "stale": 0, "failing": 0, "unknown": 0, "total": 0}


@pytest.mark.asyncio
async def test_fresh_source_classified_fresh(client: AsyncClient, session: AsyncSession):
    now = _utcnow()
    session.add(DataFreshness(
        source="ingest-edgar",
        last_successful_run=now - timedelta(minutes=10),
        last_attempt=now - timedelta(minutes=10),
        records_added_last_run=42,
        consecutive_failures=0,
        status="fresh",
        freshness_threshold_minutes=1440,
    ))
    await session.commit()

    resp = await client.get("/api/v1/data-freshness")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert len(sources) == 1
    s = sources[0]
    assert s["source"] == "ingest-edgar"
    assert s["status"] == "fresh"
    assert s["staleness_minutes"] is not None and s["staleness_minutes"] <= 11
    assert s["consecutive_failures"] == 0
    assert s["records_added_last_run"] == 42


@pytest.mark.asyncio
async def test_stale_source_classified_stale(client: AsyncClient, session: AsyncSession):
    """Last success > threshold ago → stale, even if status column says fresh."""
    now = _utcnow()
    session.add(DataFreshness(
        source="ingest-patents",
        last_successful_run=now - timedelta(days=3),  # > 1440 min default threshold
        last_attempt=now - timedelta(days=3),
        consecutive_failures=0,
        status="fresh",  # router should recompute → stale
        freshness_threshold_minutes=1440,
    ))
    await session.commit()

    resp = await client.get("/api/v1/data-freshness")
    sources = resp.json()["sources"]
    assert sources[0]["status"] == "stale"


@pytest.mark.asyncio
async def test_failing_source_overrides_freshness(client: AsyncClient, session: AsyncSession):
    """If consecutive_failures > 0 → failing, regardless of last_successful_run age."""
    now = _utcnow()
    session.add(DataFreshness(
        source="ingest-news",
        last_successful_run=now - timedelta(minutes=5),  # would normally be 'fresh'
        last_attempt=now - timedelta(minutes=1),
        consecutive_failures=3,
        status="failing",
    ))
    await session.commit()

    resp = await client.get("/api/v1/data-freshness")
    sources = resp.json()["sources"]
    assert sources[0]["status"] == "failing"
    assert sources[0]["consecutive_failures"] == 3


@pytest.mark.asyncio
async def test_unknown_when_no_successful_run(client: AsyncClient, session: AsyncSession):
    session.add(DataFreshness(
        source="ingest-trials",
        last_successful_run=None,
        last_attempt=None,
        consecutive_failures=0,
        status="unknown",
    ))
    await session.commit()

    resp = await client.get("/api/v1/data-freshness")
    sources = resp.json()["sources"]
    assert sources[0]["status"] == "unknown"
    assert sources[0]["staleness_minutes"] is None


@pytest.mark.asyncio
async def test_summary_aggregates_correctly(client: AsyncClient, session: AsyncSession):
    now = _utcnow()
    session.add_all([
        DataFreshness(source="a", last_successful_run=now - timedelta(minutes=5),
                      consecutive_failures=0, freshness_threshold_minutes=1440),
        DataFreshness(source="b", last_successful_run=now - timedelta(days=3),
                      consecutive_failures=0, freshness_threshold_minutes=1440),
        DataFreshness(source="c", last_successful_run=now - timedelta(minutes=5),
                      consecutive_failures=2, freshness_threshold_minutes=1440),
        DataFreshness(source="d", last_successful_run=None, consecutive_failures=0),
    ])
    await session.commit()

    resp = await client.get("/api/v1/data-freshness")
    summary = resp.json()["summary"]
    assert summary == {"fresh": 1, "stale": 1, "failing": 1, "unknown": 1, "total": 4}
