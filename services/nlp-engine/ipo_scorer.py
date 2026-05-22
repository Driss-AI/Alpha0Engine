"""
IPO Proximity Scorer
====================
Scores how likely a private company is to IPO within 12-24 months.
All based on FREE public data patterns.

Scoring signals (each 0-1, weighted sum):
  1. Form D frequency   (0.20) — Multiple rounds in 12mo = late stage
  2. Offering size      (0.20) — $100M+ rounds = pre-IPO
  3. Revenue indicator   (0.15) — Revenue range from Form D
  4. Investor quality    (0.15) — Known crossover funds in 13F
  5. Patent velocity     (0.10) — IP moat building
  6. GitHub activity     (0.10) — Product maturity signal
  7. Employee signals    (0.10) — CFO/GC hires with IPO experience

Score > 0.7 = "IPO likely within 18 months"
Score > 0.5 = "IPO trajectory"
Score < 0.3 = "Early stage, not close"
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

log = logging.getLogger(__name__)


class IPOProximityScorer:
    async def score_all(self) -> List[Dict[str, Any]]:
        """Score all private entities for IPO proximity."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.entities import Entity
        from shared.schemas.signals import Signal
        from sqlmodel import select

        async with AsyncSessionLocal() as session:
            result = await session.exec(
                select(Entity).where(Entity.entity_type == "private").limit(500)
            )
            entities = result.all()

        if not entities:
            return []

        candidates = []
        for entity in entities:
            score = await self._score_entity(entity)
            if score["total"] > 0.3:
                candidates.append(score)
                # Write IPO proximity signal
                await self._write_ipo_signal(entity, score)

        # Sort by score descending
        candidates.sort(key=lambda x: x["total"], reverse=True)
        log.info(f"Top IPO candidates: {[(c['name'], round(c['total'], 2)) for c in candidates[:5]]}")
        return candidates

    async def _score_entity(self, entity) -> Dict[str, Any]:
        """Calculate IPO proximity score for a single entity."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        from sqlmodel import select
        from sqlalchemy import func

        now = datetime.utcnow()
        twelve_months = now - timedelta(days=365)

        async with AsyncSessionLocal() as session:
            result = await session.exec(
                select(Signal)
                .where(Signal.entity_id == entity.id)
                .where(Signal.signal_date >= twelve_months)
            )
            signals = result.all()

        scores = {}

        # 1. Form D frequency (multiple rounds = late stage)
        form_d_signals = [s for s in signals if s.signal_type == "form_d"]
        scores["form_d_freq"] = min(len(form_d_signals) / 3.0, 1.0) * 0.20

        # 2. Offering size (large rounds = pre-IPO)
        max_offering = 0
        for s in form_d_signals:
            amt = (s.raw_data or {}).get("total_offering_amount", 0) or 0
            if isinstance(amt, (int, float)):
                max_offering = max(max_offering, amt)
        if max_offering >= 500_000_000:
            scores["offering_size"] = 1.0 * 0.20
        elif max_offering >= 100_000_000:
            scores["offering_size"] = 0.8 * 0.20
        elif max_offering >= 50_000_000:
            scores["offering_size"] = 0.5 * 0.20
        else:
            scores["offering_size"] = min(max_offering / 50_000_000, 1.0) * 0.20

        # 3. Revenue indicator from Form D
        revenue_score = 0.0
        for s in form_d_signals:
            rev = (s.raw_data or {}).get("revenue_range", "")
            if rev and ("100" in str(rev) or "exceed" in str(rev).lower()):
                revenue_score = 0.8
        scores["revenue"] = revenue_score * 0.15

        # 4. Patent velocity (IP moat)
        patent_signals = [s for s in signals if s.signal_type in ("patent_grant", "patent_filing")]
        scores["patents"] = min(len(patent_signals) / 10.0, 1.0) * 0.10

        # 5. GitHub activity
        github_signals = [s for s in signals if s.signal_type in ("github_commit", "github_star")]
        scores["github"] = min(len(github_signals) / 50.0, 1.0) * 0.10

        # 6. Crossover/investor quality
        crossover_signals = [s for s in signals if s.signal_type == "crossover_filing"]
        scores["investors"] = min(len(crossover_signals) / 2.0, 1.0) * 0.15

        # 7. Key hires
        hire_signals = [s for s in signals if s.signal_type == "job_posting"]
        scores["hires"] = min(len(hire_signals) / 5.0, 1.0) * 0.10

        total = sum(scores.values())

        return {
            "entity_id": entity.id,
            "name": entity.name,
            "total": round(total, 3),
            "breakdown": {k: round(v, 3) for k, v in scores.items()},
            "stage_estimate": (
                "pre_ipo" if total > 0.7 else
                "late_stage" if total > 0.5 else
                "growth" if total > 0.3 else
                "early"
            ),
        }

    async def _write_ipo_signal(self, entity, score: Dict) -> None:
        """Write an IPO proximity signal to the database."""
        try:
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            import uuid

            signal = Signal(
                id=str(uuid.uuid4()),
                entity_id=entity.id,
                signal_type="news_mention",  # Using existing type for IPO proximity
                signal_date=datetime.utcnow(),
                value=score["total"],
                raw_data={"ipo_proximity": score},
                source="nlp_engine",
                source_id=f"ipo-score-{entity.id}",
                notes=f"IPO proximity: {score['total']:.2f} ({score['stage_estimate']})",
            )

            async with AsyncSessionLocal() as session:
                session.add(signal)
                await session.commit()
        except Exception as e:
            log.error(f"Failed to write IPO signal for {entity.name}: {e}")
