"""
Theme Detector — HDBSCAN clustering on embeddings.
Handles case where embeddings table is empty or missing vector column.
"""
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import Counter

log = logging.getLogger(__name__)


class ThemeDetector:
    async def detect_themes(self) -> List[Dict[str, Any]]:
        from shared.clients.postgres import AsyncSessionLocal
        from sqlmodel import text

        # Check if embeddings exist
        try:
            async with AsyncSessionLocal() as session:
                count_result = await session.execute(text("SELECT COUNT(*) FROM embeddings"))
                count = count_result.scalar()
                if count < 20:
                    log.info(f"Only {count} embeddings — need 20+ for clustering. Skipping.")
                    return []

                # Check if vector column exists
                has_vector = False
                try:
                    await session.execute(text("SELECT embedding FROM embeddings LIMIT 1"))
                    has_vector = True
                except Exception:
                    await session.rollback()

                if has_vector:
                    result = await session.execute(text("""
                        SELECT id, entity_id, text, source, embedding::text, created_at
                        FROM embeddings WHERE embedding IS NOT NULL
                        ORDER BY created_at DESC LIMIT 10000
                    """))
                else:
                    # Fallback: cluster by text without vectors
                    result = await session.execute(text("""
                        SELECT id, entity_id, text, source, NULL as embedding, created_at
                        FROM embeddings
                        ORDER BY created_at DESC LIMIT 10000
                    """))
                rows = result.fetchall()
        except Exception as e:
            log.warning(f"Cannot query embeddings: {e}")
            return []

        if len(rows) < 20:
            return []

        # Parse vectors if available
        vectors = []
        metadata = []
        for row in rows:
            meta = {"id": row[0], "entity_id": row[1], "text": row[2], "source": row[3], "created_at": row[5]}
            metadata.append(meta)
            vec_str = row[4]
            if vec_str and vec_str.startswith("["):
                vec = [float(x) for x in vec_str.strip("[]").split(",")]
                vectors.append(vec)

        if len(vectors) >= 20:
            return await self._cluster_vectors(vectors, metadata)
        else:
            log.info("Not enough vectors for clustering. Using keyword-based themes.")
            return await self._keyword_themes(metadata)

    async def _cluster_vectors(self, vectors, metadata) -> List[Dict]:
        X = np.array(vectors[:len(metadata)])

        try:
            from sklearn.cluster import HDBSCAN
            labels = HDBSCAN(min_cluster_size=5, min_samples=3).fit_predict(X)
        except Exception:
            from sklearn.cluster import KMeans
            n = min(10, len(vectors) // 5)
            if n < 2: return []
            labels = KMeans(n_clusters=n, random_state=42, n_init=10).fit_predict(X)

        return self._analyze_clusters(labels, metadata)

    async def _keyword_themes(self, metadata) -> List[Dict]:
        """Simple keyword-based theme grouping when vectors aren't available."""
        # Group by source type as a basic theme
        source_groups = {}
        for m in metadata:
            src = m.get("source", "unknown")
            source_groups.setdefault(src, []).append(m)

        themes = []
        for src, members in source_groups.items():
            if len(members) < 3: continue
            all_words = []
            for m in members:
                all_words.extend(m["text"].lower().split())
            stop = {"the","a","an","and","or","of","in","to","for","with","on","at","by","from","is","it","as","this","that","are","was","be","raising","none"}
            counts = Counter(w for w in all_words if len(w) > 2 and w not in stop)
            keywords = [w for w, _ in counts.most_common(10)]
            entity_ids = list(set(m["entity_id"] for m in members))
            themes.append({
                "name": " / ".join(keywords[:3]).title(),
                "keywords": keywords,
                "velocity_score": 0.5,
                "entity_count": len(entity_ids),
                "signal_count": len(members),
                "entity_ids": entity_ids,
                "status": "active",
            })

        await self._save_themes(themes)
        return themes

    async def _analyze_clusters(self, labels, metadata) -> List[Dict]:
        cluster_ids = set(labels)
        cluster_ids.discard(-1)
        now = datetime.utcnow()
        thirty_days = timedelta(days=30)
        themes = []

        for cid in cluster_ids:
            members = [metadata[i] for i, l in enumerate(labels) if l == cid]
            if len(members) < 3: continue

            all_words = []
            for m in members:
                all_words.extend(m["text"].lower().split())
            stop = {"the","a","an","and","or","of","in","to","for","with","on","at","by","from","is","it","as","this","that","are","was","be","raising","none"}
            counts = Counter(w for w in all_words if len(w) > 2 and w not in stop)
            keywords = [w for w, _ in counts.most_common(10)]

            recent = [m for m in members if m.get("created_at") and (now - m["created_at"]) < thirty_days]
            older = [m for m in members if m.get("created_at") and thirty_days <= (now - m["created_at"]) < thirty_days * 2]
            velocity = 0.0
            if older: velocity = min(len(recent) / max(len(older), 1), 2.0) / 2.0
            elif recent: velocity = 0.8

            entity_ids = list(set(m["entity_id"] for m in members))
            themes.append({
                "name": " / ".join(keywords[:3]).title(),
                "keywords": keywords,
                "velocity_score": round(velocity, 3),
                "entity_count": len(entity_ids),
                "signal_count": len(members),
                "entity_ids": entity_ids,
                "status": "emerging" if velocity > 0.5 else "active" if velocity > 0.2 else "cooling",
            })

        await self._save_themes(themes)
        return themes

    async def _save_themes(self, themes):
        from shared.clients.postgres import AsyncSessionLocal
        from sqlmodel import text
        import uuid

        try:
            async with AsyncSessionLocal() as session:
                for t in themes:
                    import json
                    tid = str(uuid.uuid4())
                    await session.execute(text("""
                        INSERT INTO themes (id, name, keywords, velocity_score, entity_count, signal_count, status, created_at, updated_at)
                        VALUES (:id, :name, :keywords, :vel, :ec, :sc, :status, NOW(), NOW())
                    """), {"id": tid, "name": t["name"], "keywords": json.dumps(t["keywords"]),
                           "vel": t["velocity_score"], "ec": t["entity_count"],
                           "sc": t["signal_count"], "status": t["status"]})
                await session.commit()
        except Exception as e:
            log.error(f"Failed to save themes: {e}")
