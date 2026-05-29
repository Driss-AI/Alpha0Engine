"""
Embedder — generates sentence embeddings from signal text.
Uses all-MiniLM-L6-v2 (384 dims, CPU, fast).
Processes ALL signal types.
"""
import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 64


class Embedder:
    def __init__(self):
        log.info(f"Loading embedding model: {MODEL_NAME}")
        self.model = SentenceTransformer(MODEL_NAME)

    async def embed_new_signals(self) -> int:
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        from sqlmodel import select, text
        import uuid

        # Ensure table exists with vector column
        await self._ensure_table()

        async with AsyncSessionLocal() as session:
            # Get already-embedded source_ids
            try:
                existing = await session.execute(text("SELECT source_id FROM embeddings WHERE source_id IS NOT NULL"))
                existing_ids = set(r[0] for r in existing.fetchall())
            except Exception:
                existing_ids = set()

            result = await session.exec(
                select(Signal).order_by(Signal.created_at.desc()).limit(500)
            )
            signals = result.all()

        signals = [s for s in signals if s.source_id not in existing_ids]
        if not signals:
            log.info("No new signals to embed")
            return 0

        texts, refs = [], []
        for sig in signals:
            t = self._extract_text(sig)
            if t and len(t) > 5:
                texts.append(t)
                refs.append(sig)

        if not texts:
            return 0

        log.info(f"Generating embeddings for {len(texts)} texts...")
        vectors = self.model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False)

        stored = 0
        async with AsyncSessionLocal() as session:
            for i, (sig, vec) in enumerate(zip(refs, vectors)):
                vec_str = "[" + ",".join(str(float(v)) for v in vec) + "]"
                eid = sig.entity_id if sig.entity_id != "UNRESOLVED" else "unknown"
                try:
                    await session.execute(text(
                        "INSERT INTO embeddings (id, entity_id, text, source, source_id, embedding_model, dimensions, embedding, created_at) "
                        "VALUES (:id, :eid, :txt, :src, :sid, 'all-MiniLM-L6-v2', 384, CAST(:emb AS vector), NOW()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ), {
                        "id": str(uuid.uuid4()), "eid": eid,
                        "txt": texts[i][:500], "src": sig.signal_type,
                        "sid": sig.source_id, "emb": vec_str,
                    })
                    stored += 1
                except Exception as e:
                    await session.rollback()
                    log.warning(f"Embed insert failed: {e}")
                    # If vector insert fails, try without vector
                    try:
                        await session.execute(text(
                            "INSERT INTO embeddings (id, entity_id, text, source, source_id, embedding_model, dimensions, created_at) "
                            "VALUES (:id, :eid, :txt, :src, :sid, 'all-MiniLM-L6-v2', 384, NOW()) "
                            "ON CONFLICT (id) DO NOTHING"
                        ), {"id": str(uuid.uuid4()), "eid": eid,
                            "txt": texts[i][:500], "src": sig.signal_type, "sid": sig.source_id})
                        stored += 1
                    except Exception:
                        await session.rollback()
                    break  # stop on first vector failure, switch to non-vector mode

            await session.commit()

        log.info(f"Stored {stored} embeddings")
        return stored

    async def _ensure_table(self):
        """Create embeddings table with vector column."""
        from shared.clients.postgres import AsyncSessionLocal
        from sqlmodel import text

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.commit()
            except Exception:
                await session.rollback()
                log.warning("pgvector extension not available")

            # Drop and recreate if vector column is missing
            try:
                await session.execute(text("SELECT embedding FROM embeddings LIMIT 1"))
                await session.commit()
                log.info("Embeddings table with vector column exists")
            except Exception:
                await session.rollback()
                # Table exists without vector column, or doesn't exist — recreate
                log.info("Recreating embeddings table with vector column...")
                try:
                    await session.execute(text("DROP TABLE IF EXISTS embeddings"))
                    await session.execute(text("""
                        CREATE TABLE embeddings (
                            id TEXT PRIMARY KEY,
                            entity_id TEXT NOT NULL,
                            text TEXT NOT NULL,
                            source TEXT NOT NULL,
                            source_id TEXT,
                            embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
                            dimensions INTEGER DEFAULT 384,
                            embedding vector(384),
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """))
                    await session.execute(text("CREATE INDEX IF NOT EXISTS ix_emb_entity ON embeddings(entity_id)"))
                    await session.execute(text("CREATE INDEX IF NOT EXISTS ix_emb_source ON embeddings(source)"))
                    await session.commit()
                    log.info("Embeddings table created with vector column")
                except Exception as e:
                    await session.rollback()
                    log.warning(f"Could not create vector table: {e}. Creating without vectors.")
                    await session.execute(text("DROP TABLE IF EXISTS embeddings"))
                    await session.execute(text("""
                        CREATE TABLE embeddings (
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
                    await session.commit()
                    log.info("Embeddings table created WITHOUT vector column (basic mode)")

    def _extract_text(self, signal) -> str:
        rd = signal.raw_data or {}
        st = signal.signal_type

        if st in ("patent_grant", "patent_filing"):
            return f"{rd.get('patent_title', '')} {rd.get('assignee_organization', '')}".strip()
        elif st == "form_d":
            return f"{rd.get('company_name', '')} {rd.get('industry_group', '')} raising {rd.get('total_offering_amount', '')}".strip()
        elif st in ("github_commit", "github_star"):
            return f"{rd.get('org', '')} {rd.get('repo', '')} {rd.get('type', '')}".strip()
        elif st == "crossover_filing":
            return f"13F {rd.get('fund_name', '') or rd.get('fund', '')} {signal.notes or ''}".strip()
        elif st == "job_posting":
            return f"New contributor {rd.get('actor', '')} joined {rd.get('repo', '')}".strip()
        return signal.notes or ""
