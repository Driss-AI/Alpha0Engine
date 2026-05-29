"""
Entity Resolution Logic
Confidence: 1.0 (exact CIK/domain) | 0.95 (github/high-fuzzy) | 0.85 (good-fuzzy) | 0.70 (low/flagged) | new (auto-create)

Fuzzy name matching runs in the database via a pg_trgm GIN index
(migration d4e5f6a7b8c9), so resolution scales to 100K+ entities without
loading them into process memory. On non-Postgres engines (the SQLite test
DB) it falls back to an in-process rapidfuzz scan.
"""
import logging
from typing import Optional, Dict, Any, Tuple
from rapidfuzz import fuzz
import tldextract
from sqlalchemy import func, text
from sqlmodel import select

log = logging.getLogger(__name__)

# pg_trgm similarity score → resolution confidence tier
_TRGM_HIGH = 0.90   # -> 0.95 confidence
_TRGM_GOOD = 0.70   # -> 0.85 confidence
_TRGM_LOW = 0.55    # -> 0.70 confidence (flagged)


class EntityResolver:
    def __init__(self):
        # Retained only for backward compatibility with callers/tests that
        # used the old in-memory cache. No entities are cached anymore.
        self._loaded = False

    async def resolve_and_update(self, signal_data: Dict[str, Any]) -> Optional[str]:
        from shared.clients.postgres import AsyncSessionLocal

        name = (signal_data.get("company_name") or signal_data.get("issuerName") or
                signal_data.get("assignee_organization") or signal_data.get("entity_name") or "").strip()
        cik = signal_data.get("cik", "")
        domain = self._domain(signal_data.get("domain", ""))
        github_org = signal_data.get("org", "")

        async with AsyncSessionLocal() as session:
            entity_id = None
            if cik:
                entity_id = await self._by_cik(session, cik)
            if not entity_id and domain:
                entity_id = await self._by_domain(session, domain)
            if not entity_id and github_org:
                entity_id = await self._by_github(session, github_org)
            if not entity_id and name:
                entity_id, _ = await self._by_name(session, name)
            if not entity_id and name:
                entity_id = await self._create(session, name, cik, domain, github_org)
                log.info(f"New entity: {name} -> {entity_id}")

            if entity_id:
                await self._update_signal(
                    session,
                    signal_data.get("accession_number") or signal_data.get("source_id"),
                    entity_id,
                )
            else:
                log.warning(f"Could not resolve: {name}")

        return entity_id

    async def _by_cik(self, session, cik: str) -> Optional[str]:
        from shared.schemas.entities import Entity
        return (await session.exec(
            select(Entity.id).where(Entity.cik == cik).limit(1)
        )).first()

    async def _by_domain(self, session, domain: str) -> Optional[str]:
        from shared.schemas.entities import Entity
        return (await session.exec(
            select(Entity.id).where(Entity.domain == domain).limit(1)
        )).first()

    async def _by_github(self, session, org: str) -> Optional[str]:
        from shared.schemas.entities import Entity
        return (await session.exec(
            select(Entity.id).where(func.lower(Entity.github_org) == org.lower()).limit(1)
        )).first()

    async def _by_name(self, session, name: str) -> Tuple[Optional[str], float]:
        if self._is_postgres():
            return await self._by_name_trgm(session, name)
        return await self._by_name_fuzzy(session, name)

    async def _by_name_trgm(self, session, name: str) -> Tuple[Optional[str], float]:
        """Postgres path: pg_trgm similarity, served by the GIN index."""
        sql = text(
            "SELECT id, similarity(lower(name), lower(:q)) AS sim "
            "FROM entities WHERE lower(name) % lower(:q) "
            "ORDER BY sim DESC LIMIT 1"
        )
        row = (await session.execute(sql, {"q": name})).first()
        if not row:
            return None, 0.0
        eid, sim = row[0], float(row[1])
        if sim >= _TRGM_HIGH:
            return eid, 0.95
        if sim >= _TRGM_GOOD:
            return eid, 0.85
        if sim >= _TRGM_LOW:
            return eid, 0.70
        return None, 0.0

    async def _by_name_fuzzy(self, session, name: str) -> Tuple[Optional[str], float]:
        """Fallback path (SQLite/tests): in-process rapidfuzz over all names."""
        from shared.schemas.entities import Entity
        rows = (await session.exec(select(Entity.id, Entity.name))).all()
        best_score, best_id = 0.0, None
        nl = name.lower()
        for eid, ename in rows:
            score = fuzz.token_sort_ratio(nl, (ename or "").lower())
            if score > best_score:
                best_score, best_id = score, eid
        if best_score >= 95:
            return best_id, 0.95
        if best_score >= 85:
            return best_id, 0.85
        if best_score >= 75:
            return best_id, 0.70
        return None, 0.0

    @staticmethod
    def _is_postgres() -> bool:
        from shared.clients.postgres import engine
        return engine.dialect.name == "postgresql"

    async def _create(self, session, name: str, cik: str, domain: str, github_org: str) -> str:
        from shared.schemas.entities import Entity
        entity = Entity(name=name, cik=cik or None, domain=domain or None,
                        github_org=github_org or None, entity_type="private", resolution_confidence=0.7)
        session.add(entity)
        await session.commit()
        await session.refresh(entity)
        return entity.id

    async def _update_signal(self, session, source_id: Optional[str], entity_id: str):
        if not source_id:
            return
        try:
            from shared.schemas.signals import Signal
            from sqlmodel import update
            await session.exec(
                update(Signal)
                .where(Signal.source_id == source_id)
                .where(Signal.resolution_status == "pending")
                .values(entity_id=entity_id, resolution_status="resolved")
            )
            await session.commit()
        except Exception as e:
            log.error(f"Signal update failed for source_id={source_id}: {e}")

    async def _refresh(self):
        """Deprecated no-op — entities are no longer cached in memory.
        Kept so existing callers/tests that pre-warmed the cache still work."""
        self._loaded = True

    @staticmethod
    def _domain(raw: str) -> str:
        if not raw:
            return ""
        ex = tldextract.extract(raw)
        return f"{ex.domain}.{ex.suffix}" if ex.domain and ex.suffix else raw.lower().strip()
