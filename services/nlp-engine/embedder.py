"""
Embedder
========
Generates sentence embeddings from signal text data.
Uses all-MiniLM-L6-v2 (384 dims, fast, runs on CPU).

Sources embedded:
  - Patent titles + abstracts (from USPTO signals)
  - Form D company names + industry descriptions
  - Academic paper titles (from citation signals, Module 2 future)
"""
import logging
import json
from typing import List, Dict, Any
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
        """Find signals without embeddings and generate them."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        from shared.schemas.embeddings import Embedding
        from sqlmodel import select, text

        async with AsyncSessionLocal() as session:
            # Find signals that haven't been embedded yet
            result = await session.exec(
                select(Signal)
                .where(Signal.signal_type.in_(["patent_grant", "patent_filing", "form_d"]))
                .where(Signal.entity_id != "UNRESOLVED")
                .order_by(Signal.created_at.desc())
                .limit(500)
            )
            signals = result.all()

        if not signals:
            log.info("No new signals to embed")
            return 0

        # Extract text from signals
        texts = []
        signal_refs = []
        for sig in signals:
            text_content = self._extract_text(sig)
            if text_content:
                texts.append(text_content)
                signal_refs.append(sig)

        if not texts:
            return 0

        # Generate embeddings in batches
        log.info(f"Generating embeddings for {len(texts)} texts...")
        all_embeddings = self.model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False)

        # Store in database
        stored = 0
        async with AsyncSessionLocal() as session:
            # Ensure pgvector extension exists
            await session.exec(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

            # Create embeddings table with vector column if not exists
            await session.exec(text("""
                CREATE TABLE IF NOT EXISTS embeddings (
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
            await session.exec(text("""
                CREATE INDEX IF NOT EXISTS ix_embeddings_entity ON embeddings(entity_id)
            """))
            await session.commit()

            for i, (sig, vec) in enumerate(zip(signal_refs, all_embeddings)):
                import uuid
                vec_str = "[" + ",".join(str(float(v)) for v in vec) + "]"
                await session.exec(text("""
                    INSERT INTO embeddings (id, entity_id, text, source, source_id, embedding, created_at)
                    VALUES (:id, :entity_id, :text, :source, :source_id, :embedding::vector, NOW())
                    ON CONFLICT (id) DO NOTHING
                """), {
                    "id": str(uuid.uuid4()),
                    "entity_id": sig.entity_id,
                    "text": texts[i][:500],
                    "source": sig.signal_type,
                    "source_id": sig.source_id,
                    "embedding": vec_str,
                })
                stored += 1

            await session.commit()

        log.info(f"Stored {stored} embeddings")
        return stored

    def _extract_text(self, signal) -> str:
        """Pull meaningful text from a signal's raw_data."""
        rd = signal.raw_data or {}

        if signal.signal_type in ("patent_grant", "patent_filing"):
            title = rd.get("patent_title", "")
            assignee = rd.get("assignee_organization", "")
            cpc = rd.get("cpc_group_id", "")
            return f"{title} {assignee} {cpc}".strip()

        elif signal.signal_type == "form_d":
            name = rd.get("company_name", "")
            industry = rd.get("industry_group", "")
            state = rd.get("state_of_incorporation", "")
            amount = rd.get("total_offering_amount", "")
            return f"{name} {industry} {state} raising {amount}".strip()

        return ""

    def encode_query(self, query: str) -> List[float]:
        """Encode a search query for semantic similarity search."""
        return self.model.encode(query).tolist()
