"""
Embedder — generates sentence embeddings from signal text.
Uses all-MiniLM-L6-v2 (384 dims, CPU, fast).

Now processes ALL signal types, not just patents/form_d.
"""
import logging
from typing import List
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 64


class Embedder:
    def __init__(self):
        log.info(f"Loading embedding model: {MODEL_NAME}")
        self.model = SentenceTransformer(MODEL_NAME)
        self.dimensions = 384

    async def embed_new_signals(self) -> int:
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        from sqlmodel import select, text
        import uuid

        async with AsyncSessionLocal() as session:
            # Get signals that haven't been embedded yet
            # Check which source_ids already have embeddings
            try:
                existing = await session.exec(text("SELECT source_id FROM embeddings WHERE source_id IS NOT NULL"))
                existing_ids = set(r[0] for r in existing.all())
            except Exception:
                existing_ids = set()

            result = await session.exec(
                select(Signal)
                .where(Signal.entity_id != "UNRESOLVED")
                .order_by(Signal.created_at.desc())
                .limit(500)
            )
            signals = result.all()

        # Filter out already-embedded
        signals = [s for s in signals if s.source_id not in existing_ids]

        if not signals:
            log.info("No new signals to embed")
            return 0

        texts = []
        signal_refs = []
        for sig in signals:
            t = self._extract_text(sig)
            if t and len(t) > 5:
                texts.append(t)
                signal_refs.append(sig)

        if not texts:
            return 0

        log.info(f"Generating embeddings for {len(texts)} texts...")
        all_embeddings = self.model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False)

        stored = 0
        async with AsyncSessionLocal() as session:
            # Ensure pgvector + table exist
            try:
                await session.exec(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.commit()
            except Exception:
                await session.rollback()

            await session.exec(text("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT,
                    embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
                    dimensions INTEGER DEFAULT 384,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            try:
                await session.exec(text("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding vector(384)"))
            except Exception:
                await session.rollback()
            await session.commit()

            for i, (sig, vec) in enumerate(zip(signal_refs, all_embeddings)):
                vec_str = "[" + ",".join(str(float(v)) for v in vec) + "]"
                try:
                    await session.exec(text("""
                        INSERT INTO embeddings (id, entity_id, text, source, source_id, embedding, created_at)
                        VALUES (:id, :eid, :txt, :src, :sid, :emb::vector, NOW())
                        ON CONFLICT (id) DO NOTHING
                    """), {
                        "id": str(uuid.uuid4()),
                        "eid": sig.entity_id,
                        "txt": texts[i][:500],
                        "src": sig.signal_type,
                        "sid": sig.source_id,
                        "emb": vec_str,
                    })
                    stored += 1
                except Exception as e:
                    await session.rollback()
                    log.debug(f"Embed insert error: {e}")

            await session.commit()

        log.info(f"Stored {stored} embeddings")
        return stored

    def _extract_text(self, signal) -> str:
        rd = signal.raw_data or {}
        st = signal.signal_type

        if st in ("patent_grant", "patent_filing"):
            title = rd.get("patent_title", "")
            assignee = rd.get("assignee_organization", "")
            return f"{title} {assignee}".strip()

        elif st == "form_d":
            name = rd.get("company_name", "")
            industry = rd.get("industry_group", "")
            amount = rd.get("total_offering_amount", "")
            return f"{name} {industry} raising {amount}".strip()

        elif st in ("github_commit", "github_star"):
            repo = rd.get("repo", "")
            org = rd.get("org", "")
            event_type = rd.get("type", "")
            return f"{org} {repo} {event_type}".strip()

        elif st == "crossover_filing":
            fund = rd.get("fund_name", "") or rd.get("fund", "")
            notes = signal.notes or ""
            return f"13F {fund} {notes}".strip()

        elif st == "job_posting":
            actor = rd.get("actor", "")
            repo = rd.get("repo", "")
            return f"New contributor {actor} joined {repo}".strip()

        return signal.notes or ""
