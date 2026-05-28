"""
Entity Resolver unit tests.
Tests fuzzy matching, CIK/domain/github resolution, and new entity creation.
Uses the test SQLite DB from conftest via module stubbing.
"""
import sys
import os
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.entities import Entity
from shared.schemas.signals import Signal

RESOLVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "entity-resolver"))
if RESOLVER_DIR not in sys.path:
    sys.path.insert(0, RESOLVER_DIR)

from resolver import EntityResolver


async def _seed_entities(session: AsyncSession) -> list[Entity]:
    entities = [
        Entity(id="ent-1", name="Apple Inc", ticker="AAPL", cik="0000320193",
               domain="apple.com", github_org="apple", entity_type="public"),
        Entity(id="ent-2", name="Tesla Inc", ticker="TSLA", cik="0001318605",
               domain="tesla.com", entity_type="public"),
        Entity(id="ent-3", name="Moderna Inc", ticker="MRNA", cik="0001682852",
               domain="modernatx.com", github_org="modernatx", entity_type="public"),
    ]
    for e in entities:
        session.add(e)
    await session.commit()
    return entities


@pytest.mark.asyncio
async def test_resolve_by_cik(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"cik": "0000320193", "company_name": "Apple"})
    assert entity_id == "ent-1"


@pytest.mark.asyncio
async def test_resolve_by_domain(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"domain": "https://tesla.com/about", "company_name": "Tesla"})
    assert entity_id == "ent-2"


@pytest.mark.asyncio
async def test_resolve_by_github_org(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"org": "apple", "company_name": "Apple"})
    assert entity_id == "ent-1"


@pytest.mark.asyncio
async def test_resolve_by_fuzzy_name_exact(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"company_name": "Apple Inc"})
    assert entity_id == "ent-1"


@pytest.mark.asyncio
async def test_resolve_by_fuzzy_name_close(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"company_name": "Apple Inc."})
    assert entity_id == "ent-1"


@pytest.mark.asyncio
async def test_resolve_creates_new_entity(session: AsyncSession):
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({"company_name": "Totally New Startup LLC"})
    assert entity_id is not None
    assert entity_id not in ("ent-1", "ent-2", "ent-3")

    new_entity = await session.get(Entity, entity_id)
    assert new_entity is not None
    assert new_entity.name == "Totally New Startup LLC"
    assert new_entity.resolution_confidence == 0.7


@pytest.mark.asyncio
async def test_resolve_empty_name_no_identifiers(session: AsyncSession):
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({})
    assert entity_id is None


@pytest.mark.asyncio
async def test_cik_takes_priority_over_fuzzy(session: AsyncSession):
    """CIK match should win even if name is closer to a different entity."""
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({
        "cik": "0001318605",
        "company_name": "Apple Inc",
    })
    assert entity_id == "ent-2"


@pytest.mark.asyncio
async def test_domain_extraction(session: AsyncSession):
    """Resolver should extract base domain from full URLs."""
    await _seed_entities(session)
    resolver = EntityResolver()
    await resolver._refresh()

    entity_id = await resolver.resolve_and_update({
        "domain": "https://www.modernatx.com/research",
        "company_name": "Moderna",
    })
    assert entity_id == "ent-3"


@pytest.mark.asyncio
async def test_signal_update_on_resolve(session: AsyncSession):
    """Resolver should update signal's entity_id and resolution_status."""
    await _seed_entities(session)

    from datetime import datetime
    signal = Signal(
        entity_id="UNRESOLVED", signal_type="form_d",
        signal_date=datetime(2026, 1, 1), source="edgar",
        source_id="ACC-123", resolution_status="pending",
    )
    session.add(signal)
    await session.commit()
    await session.refresh(signal)

    resolver = EntityResolver()
    await resolver._refresh()

    await resolver.resolve_and_update({
        "cik": "0000320193",
        "company_name": "Apple",
        "accession_number": "ACC-123",
    })

    await session.refresh(signal)
    assert signal.entity_id == "ent-1"
    assert signal.resolution_status == "resolved"
