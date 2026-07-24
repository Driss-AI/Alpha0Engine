"""Existing junk in the entities table gets corrected, not just new arrivals.

Discovery originally stored every SEC ticker as `entity_type="public"`, so the
database still holds thousands of warrants, units and ADRs that the screener
scores on every run. `reclassify_existing_universe` heals those in place.
"""
import asyncio

from shared.universe import EXCLUDED_ENTITY_TYPE, SCANNABLE_ENTITY_TYPE


def _reclassify(seed):
    """Seed entities into a fresh in-memory DB, reclassify, return the result."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel, select
    from sqlmodel.ext.asyncio.session import AsyncSession
    from shared.schemas.entities import Entity
    import main as prices_main

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine) as session:
            for ticker, name, etype in seed:
                session.add(Entity(name=name, ticker=ticker, cik="1", entity_type=etype))
            await session.commit()

            changed = await prices_main.reclassify_existing_universe(session)

            rows = (await session.exec(select(Entity))).all()
            return changed, {r.ticker: r.entity_type for r in rows}

    return asyncio.run(scenario())


class TestReclassifyExistingUniverse:
    def test_junk_stored_as_public_gets_excluded(self):
        changed, types = _reclassify([
            ("XRPNW", "Armada Acquisition Corp. II", SCANNABLE_ENTITY_TYPE),
            ("QUMSU", "Quantumsphere Acquisition Corp", SCANNABLE_ENTITY_TYPE),
            ("KXHCF", "Kioxia Holdings Corporation/ADR", SCANNABLE_ENTITY_TYPE),
            ("SPRB", "Spruce Biosciences Inc", SCANNABLE_ENTITY_TYPE),
        ])
        assert changed == 3
        assert types["XRPNW"] == EXCLUDED_ENTITY_TYPE
        assert types["QUMSU"] == EXCLUDED_ENTITY_TYPE
        assert types["KXHCF"] == EXCLUDED_ENTITY_TYPE
        assert types["SPRB"] == SCANNABLE_ENTITY_TYPE   # the candidate survives

    def test_is_idempotent(self):
        seed = [("XRPNW", "Armada Acquisition Corp. II", EXCLUDED_ENTITY_TYPE),
                ("SPRB", "Spruce Biosciences Inc", SCANNABLE_ENTITY_TYPE)]
        changed, types = _reclassify(seed)
        assert changed == 0                              # already correct, no churn
        assert types["SPRB"] == SCANNABLE_ENTITY_TYPE

    def test_wrongly_excluded_entity_is_restored(self):
        """The filter runs both ways, so tightening a rule is reversible."""
        changed, types = _reclassify([
            ("URGN", "UroGen Pharma Ltd", EXCLUDED_ENTITY_TYPE),
        ])
        assert changed == 1
        assert types["URGN"] == SCANNABLE_ENTITY_TYPE

    def test_hand_set_types_are_never_clobbered(self):
        """A private/manually-typed entity is outside this filter's remit."""
        changed, types = _reclassify([
            ("XRPNW", "Armada Acquisition Corp. II", "private"),
        ])
        assert changed == 0
        assert types["XRPNW"] == "private"


class TestDiscoveryStillHealsWhenNothingIsNew:
    """The steady state is "no new tickers" — the filter must still apply.

    Production ran with all 10,426 SEC symbols already tracked, so discovery hit
    its "universe is up to date" path and returned before reclassifying. The
    security filter was live in the code and dead in the database.
    """

    def test_reclassify_runs_with_zero_new_tickers(self, monkeypatch):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from shared.schemas.entities import Entity
        import main as prices_main

        # Every SEC ticker is already in the table → new_entries is empty.
        sec_list = [
            {"ticker": "XRPNW", "company_name": "Armada Acquisition Corp. II", "cik": "1"},
            {"ticker": "SPRB", "company_name": "Spruce Biosciences Inc", "cik": "2"},
        ]
        monkeypatch.setattr(prices_main, "fetch_universe_tickers_sec", lambda: sec_list)

        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            session_holder = AsyncSession(engine)
            async with session_holder as session:
                for entry in sec_list:
                    session.add(Entity(name=entry["company_name"], ticker=entry["ticker"],
                                       cik=entry["cik"], entity_type="public"))
                await session.commit()

            # Point the worker's session factory at this in-memory engine.
            class _Factory:
                def __call__(self):
                    return AsyncSession(engine)

            monkeypatch.setattr(prices_main, "AsyncSessionLocal", _Factory())
            monkeypatch.setattr(prices_main, "create_db_and_tables",
                                lambda: asyncio.sleep(0))

            await prices_main.run_universe_discovery()

            async with AsyncSession(engine) as session:
                rows = (await session.exec(select(Entity))).all()
                return {r.ticker: r.entity_type for r in rows}

        types = asyncio.run(scenario())
        # The warrant that was already stored as "public" must now be excluded.
        assert types["XRPNW"] == EXCLUDED_ENTITY_TYPE
        assert types["SPRB"] == SCANNABLE_ENTITY_TYPE
