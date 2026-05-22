"""
Theme Detector
==============
Clusters embeddings using HDBSCAN to find emerging technology themes.
Scores velocity (how fast a cluster is growing).

Velocity formula:
  velocity = (signals_last_30d / signals_prev_30d) * cluster_size_weight

Themes with velocity > 0.7 are flagged as "emerging megatrends".
"""
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import Counter

log = logging.getLogger(__name__)


class ThemeDetector:
    async def detect_themes(self) -> List[Dict[str, Any]]:
        """Run HDBSCAN clustering on all embeddings, score velocity."""
        from shared.clients.postgres import AsyncSessionLocal
        from sqlmodel import text

        async with AsyncSessionLocal() as session:
            # Pull all embeddings
            result = await session.exec(text("""
                SELECT id, entity_id, text, source, embedding::text, created_at
                FROM embeddings
                ORDER BY created_at DESC
                LIMIT 10000
            """))
            rows = result.all()

        if len(rows) < 20:
            log.info(f"Only {len(rows)} embeddings — need 20+ for clustering")
            return []

        # Parse vectors
        vectors = []
        metadata = []
        for row in rows:
            vec_str = row[4]  # embedding::text
            if vec_str and vec_str.startswith("["):
                vec = [float(x) for x in vec_str.strip("[]").split(",")]
                vectors.append(vec)
                metadata.append({
                    "id": row[0], "entity_id": row[1],
                    "text": row[2], "source": row[3],
                    "created_at": row[5]
                })

        if len(vectors) < 20:
            return []

        X = np.array(vectors)

        # Run HDBSCAN clustering
        try:
            import hdbscan
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=5,
                min_samples=3,
                metric="euclidean",
                cluster_selection_method="eom"
            )
            labels = clusterer.fit_predict(X)
        except Exception as e:
            log.error(f"HDBSCAN clustering failed: {e}")
            # Fallback to KMeans
            from sklearn.cluster import KMeans
            n_clusters = min(10, len(vectors) // 5)
            if n_clusters < 2:
                return []
            labels = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(X)

        # Analyze clusters
        cluster_ids = set(labels)
        cluster_ids.discard(-1)  # Remove noise cluster

        themes = []
        now = datetime.utcnow()
        thirty_days = timedelta(days=30)

        for cid in cluster_ids:
            members = [metadata[i] for i, l in enumerate(labels) if l == cid]
            if len(members) < 3:
                continue

            # Extract keywords from cluster texts
            all_words = []
            for m in members:
                all_words.extend(m["text"].lower().split())
            # Filter common words
            stop_words = {"the","a","an","and","or","of","in","to","for","with","on","at","by","from","is","it","as","this","that","are","was","be"}
            word_counts = Counter(w for w in all_words if len(w) > 2 and w not in stop_words)
            top_keywords = [w for w, _ in word_counts.most_common(10)]

            # Calculate velocity
            recent = [m for m in members if m["created_at"] and (now - m["created_at"]) < thirty_days]
            older = [m for m in members if m["created_at"] and thirty_days <= (now - m["created_at"]) < thirty_days * 2]
            velocity = 0.0
            if older:
                velocity = min(len(recent) / max(len(older), 1), 2.0) / 2.0
            elif recent:
                velocity = 0.8  # New cluster with only recent signals = high velocity

            # Unique entities
            entity_ids = list(set(m["entity_id"] for m in members))

            theme_data = {
                "name": " / ".join(top_keywords[:3]).title(),
                "keywords": top_keywords,
                "velocity_score": round(velocity, 3),
                "entity_count": len(entity_ids),
                "signal_count": len(members),
                "entity_ids": entity_ids,
                "status": "emerging" if velocity > 0.5 else "active" if velocity > 0.2 else "cooling",
            }
            themes.append(theme_data)

        # Write themes to database
        await self._save_themes(themes)

        log.info(f"Detected {len(themes)} themes, {sum(1 for t in themes if t['velocity_score'] > 0.5)} emerging")
        return themes

    async def _save_themes(self, themes: List[Dict]) -> None:
        """Upsert themes into the database."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.themes import Theme, ThemeEntity
        from datetime import datetime
        import uuid

        async with AsyncSessionLocal() as session:
            for t in themes:
                theme = Theme(
                    id=str(uuid.uuid4()),
                    name=t["name"],
                    keywords=t["keywords"],
                    velocity_score=t["velocity_score"],
                    entity_count=t["entity_count"],
                    signal_count=t["signal_count"],
                    status=t["status"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                session.add(theme)

                # Map entities to theme
                for eid in t.get("entity_ids", []):
                    te = ThemeEntity(
                        id=str(uuid.uuid4()),
                        theme_id=theme.id,
                        entity_id=eid,
                        similarity_score=t["velocity_score"],
                        created_at=datetime.utcnow(),
                    )
                    session.add(te)

            await session.commit()
