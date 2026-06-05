"""
Alert Engine Worker (Sprint 9.6) — private Telegram dispatcher.

Reads candidates the screener bucketed as DEEP_DIVE or SETUP_READY, assembles the
mandatory alert (thesis + evidence + 5-axis scores + red flags + why-now), dedupes
against the last 7 days, sends to a private Telegram channel, and records the
alert (for S10 outcome tracking).

Runs daily, after the screener. No-ops gracefully if Telegram isn't configured —
alerts are still recorded with delivered=False so nothing is lost.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.evidence_item import EvidenceItem
from shared.schemas.catalyst_event import CatalystEvent
from shared.schemas.alert import Alert
from shared.lanes import get_lane
from shared.scoring import build_thesis, is_alertable
from shared.services.alert_outcomes import populate_alert_returns

from alert_formatter import format_alert, build_dedupe_key
import telegram_client

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("alert-engine")

DEDUPE_DAYS = 7
# Re-alert within the dedupe window only if composite moved at least this much.
MATERIAL_MOVE = 0.10


async def _recent_alert(session: AsyncSession, dedupe_key_parts) -> Alert | None:
    ticker, lane_id, bucket = dedupe_key_parts
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=DEDUPE_DAYS)
    q = select(Alert).where(
        Alert.ticker == ticker,
        Alert.bucket == bucket,
        Alert.sent_at >= cutoff,
    )
    if lane_id:
        q = q.where(Alert.lane_id == lane_id)
    return (await session.exec(q.order_by(Alert.sent_at.desc()))).first()


async def _evidence_for(session: AsyncSession, entity_id: str, lane_id: str | None) -> list[dict]:
    rows = (await session.exec(
        select(EvidenceItem).where(
            EvidenceItem.entity_id == entity_id,
            EvidenceItem.lane_id == lane_id,
        ).limit(8)
    )).all()
    return [{"summary": r.summary, "source_url": r.source_url, "source": r.source} for r in rows]


async def _nearest_catalyst(session: AsyncSession, ticker: str) -> dict | None:
    today = datetime.now(timezone.utc).date()
    rows = (await session.exec(
        select(CatalystEvent).where(
            CatalystEvent.ticker == ticker,
            CatalystEvent.status == "upcoming",
        ).order_by(CatalystEvent.expected_date)
    )).all()
    for r in rows:
        if r.expected_date and r.expected_date >= today:
            return {"catalyst_type": r.catalyst_type, "expected_date": r.expected_date,
                    "title": r.title}
    return None


async def run_alert_dispatch():
    """Build + dispatch alerts for DEEP_DIVE / SETUP_READY candidates."""
    logger.info("=" * 60)
    logger.info("ALERT ENGINE — Starting dispatch run")
    logger.info(f"Telegram configured: {telegram_client.is_configured()}")
    logger.info("=" * 60)

    await create_db_and_tables()

    sent = 0
    skipped_dupe = 0
    recorded = 0

    async with AsyncSessionLocal() as session:
        candidates = (await session.exec(
            select(EquityScreen).where(
                EquityScreen.bucket.in_(["DEEP_DIVE", "SETUP_READY"])  # type: ignore
            ).order_by(EquityScreen.opportunity_score.desc()).limit(100)
        )).all()
        logger.info(f"Found {len(candidates)} alertable candidates")

        for c in candidates:
            if not c.bucket or not is_alertable(c.bucket) or not c.ticker:
                continue

            lane_id = c.best_lane_id
            dedupe_parts = (c.ticker, lane_id, c.bucket)

            prior = await _recent_alert(session, dedupe_parts)
            if prior is not None:
                moved = abs((c.composite_score or 0) - (prior.composite_score or 0))
                if moved < MATERIAL_MOVE:
                    skipped_dupe += 1
                    continue

            # Assemble thesis from stored lane context + evidence + nearest catalyst
            bottlenecks = []
            raw = c.raw_data or {}
            for ln in raw.get("lanes", []):
                if ln.get("lane_id") == lane_id:
                    bottlenecks = ln.get("bottleneck_exposure", [])
                    break

            evidence = await _evidence_for(session, c.entity_id, lane_id)
            catalyst = await _nearest_catalyst(session, c.ticker)

            try:
                lane_name = get_lane(lane_id).name if lane_id else "—"
            except Exception:
                lane_name = "—"

            if lane_id:
                thesis = build_thesis(
                    ticker=c.ticker, company=c.company_name, lane_id=lane_id,
                    bottlenecks=bottlenecks, evidence=evidence,
                    nearest_catalyst=catalyst,
                    short_pct_float=c.short_pct_float,
                ).to_dict()
            else:
                thesis = {"megatrend": "—", "bottleneck": "—", "exposure": c.company_name or c.ticker,
                          "evidence": evidence, "why_now": "No lane match.",
                          "catalyst_type": None, "catalyst_date": None}

            axes = (raw.get("axes") or {})
            message = format_alert(
                ticker=c.ticker, company=c.company_name, lane_name=lane_name,
                thesis=thesis, axes=axes, bucket=c.bucket,
                red_flags=raw.get("red_flags", []),
                mechanics={"float": c.float_shares, "short_pct_float": c.short_pct_float},
            )

            delivered = await telegram_client.send_message(message)
            session.add(Alert(
                ticker=c.ticker, entity_id=c.entity_id, lane_id=lane_id, bucket=c.bucket,
                composite_score=c.composite_score,
                opportunity_score=c.opportunity_score, risk_score=c.risk_score,
                timing_score=c.timing_score, why_now=thesis.get("why_now"),
                message=message, delivered=delivered,
                payload={"dedupe_key": build_dedupe_key(c.ticker, lane_id, c.bucket)},
            ))
            recorded += 1
            if delivered:
                sent += 1
                logger.info(f"  ✈ alert sent: {c.ticker} [{c.bucket}] {lane_name}")

        await session.commit()

        # S11.5: close the feedback loop — fill forward returns on matured alerts.
        matured = 0
        try:
            matured = await populate_alert_returns(session)
            if matured:
                logger.info(f"Updated forward returns on {matured} matured alert(s)")
        except Exception as e:
            logger.error(f"populate_alert_returns failed: {e}")

    logger.info("=" * 60)
    logger.info(f"ALERT DISPATCH COMPLETE — {recorded} recorded, {sent} delivered, "
                f"{skipped_dupe} deduped, {matured} outcomes updated")
    logger.info("=" * 60)
    return {"records_processed": recorded,
            "metadata": {"sent": sent, "deduped": skipped_dupe, "outcomes_updated": matured}}


async def run_loop():
    import time as _time
    from shared.clients.heartbeat import report_heartbeat
    while True:
        _start = _time.time()
        try:
            await run_alert_dispatch()
            await report_heartbeat("alert-engine", duration_seconds=_time.time() - _start, interval_hours=24)
        except Exception as e:
            logger.error(f"Alert dispatch failed: {e}")
            await report_heartbeat("alert-engine", error=str(e), interval_hours=24)
        logger.info("Next alert dispatch in 24 hours...")
        await asyncio.sleep(86400)


if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        from shared.worker_runner import run_once_with_tracking
        asyncio.run(run_once_with_tracking("alert-engine", run_alert_dispatch))
    else:
        asyncio.run(run_loop())
