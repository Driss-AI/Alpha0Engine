"""
Entity Resolution Logic
Confidence: 1.0 (exact CIK/domain) | 0.95 (github/high-fuzzy) | 0.85 (good-fuzzy) | 0.70 (low/flagged) | new (auto-create)
"""
import logging
from typing import Optional, Dict, Any, List, Tuple
from rapidfuzz import fuzz
import tldextract

log = logging.getLogger(__name__)


class EntityResolver:
    def __init__(self):
        self._cache: List[Dict] = []
        self._loaded = False

    async def resolve_and_update(self, signal_data: Dict[str, Any]) -> Optional[str]:
        await self._ensure_cache()
        name = (signal_data.get("company_name") or signal_data.get("issuerName") or
                signal_data.get("assignee_organization") or signal_data.get("entity_name") or "").strip()
        cik = signal_data.get("cik","")
        domain = self._domain(signal_data.get("domain",""))
        github_org = signal_data.get("org","")

        entity_id = None
        if cik: entity_id, _ = self._by_cik(cik)
        if not entity_id and domain: entity_id, _ = self._by_domain(domain)
        if not entity_id and github_org: entity_id, _ = self._by_github(github_org)
        if not entity_id and name: entity_id, _ = self._by_name(name)
        if not entity_id and name:
            entity_id = await self._create(name, cik, domain, github_org)
            log.info(f"New entity: {name} -> {entity_id}")

        if entity_id:
            await self._update_signal(signal_data.get("accession_number") or signal_data.get("source_id"), entity_id)
        else:
            log.warning(f"Could not resolve: {name}")
        return entity_id

    def _by_cik(self, cik: str) -> Tuple[Optional[str], float]:
        for e in self._cache:
            if e.get("cik") == cik: return e["id"], 1.0
        return None, 0.0

    def _by_domain(self, domain: str) -> Tuple[Optional[str], float]:
        for e in self._cache:
            if e.get("domain") == domain: return e["id"], 1.0
        return None, 0.0

    def _by_github(self, org: str) -> Tuple[Optional[str], float]:
        ol = org.lower()
        for e in self._cache:
            if (e.get("github_org") or "").lower() == ol: return e["id"], 0.95
        return None, 0.0

    def _by_name(self, name: str) -> Tuple[Optional[str], float]:
        best_score, best_id = 0, None
        for e in self._cache:
            score = fuzz.token_sort_ratio(name.lower(), e["name"].lower())
            if score > best_score: best_score, best_id = score, e["id"]
        if best_score >= 95: return best_id, 0.95
        if best_score >= 85: return best_id, 0.85
        if best_score >= 75: return best_id, 0.70
        return None, 0.0

    async def _ensure_cache(self):
        if not self._loaded or not self._cache:
            await self._refresh()

    async def _refresh(self):
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.entities import Entity
        from sqlmodel import select
        async with AsyncSessionLocal() as s:
            result = await s.exec(select(Entity).limit(50000))
            entities = result.all()
        self._cache = [{"id": e.id, "name": e.name, "domain": e.domain or "",
                        "cik": e.cik or "", "github_org": e.github_org or ""} for e in entities]
        self._loaded = True
        log.info(f"Entity cache: {len(self._cache)} entities")

    async def _create(self, name: str, cik: str, domain: str, github_org: str) -> str:
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.entities import Entity
        entity = Entity(name=name, cik=cik or None, domain=domain or None,
                        github_org=github_org or None, entity_type="private", resolution_confidence=0.7)
        async with AsyncSessionLocal() as s:
            s.add(entity)
            await s.commit()
            await s.refresh(entity)
        self._loaded = False
        return entity.id

    async def _update_signal(self, source_id: Optional[str], entity_id: str):
        if not source_id: return
        try:
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            from sqlmodel import update
            async with AsyncSessionLocal() as s:
                await s.exec(update(Signal).where(Signal.source_id == source_id).where(Signal.entity_id == "UNRESOLVED").values(entity_id=entity_id))
                await s.commit()
        except Exception as e:
            log.error(f"Signal update failed: {e}")

    @staticmethod
    def _domain(raw: str) -> str:
        if not raw: return ""
        ex = tldextract.extract(raw)
        return f"{ex.domain}.{ex.suffix}" if ex.domain and ex.suffix else raw.lower().strip()
