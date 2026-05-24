"""
Pipeline Heartbeat
===================
One-line helper for any worker to report health status.

Usage in any worker:
    from shared.clients.heartbeat import report_heartbeat

    # After successful run:
    await report_heartbeat("ingest-prices", records=1500, interval_hours=24)

    # After failed run:
    await report_heartbeat("ingest-prices", error="SEC API timeout", interval_hours=24)
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from sqlmodel import select
from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.pipeline_health import PipelineHealth

logger = logging.getLogger(__name__)


async def report_heartbeat(
    pipeline_name: str,
    records: int = 0,
    error: Optional[str] = None,
    interval_hours: float = 24.0,
    duration_seconds: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Report pipeline health after a run cycle.
    Call this at the end of every worker's main loop iteration.
    """
    try:
        async with AsyncSessionLocal() as session:
            # Find or create health record
            result = await session.exec(
                select(PipelineHealth).where(
                    PipelineHealth.pipeline_name == pipeline_name
                )
            )
            health = result.first()

            now = datetime.utcnow()

            if not health:
                health = PipelineHealth(
                    pipeline_name=pipeline_name,
                    expected_interval_hours=interval_hours,
                    created_at=now,
                )

            health.last_run_at = now
            health.run_count += 1
            health.run_duration_seconds = duration_seconds
            health.expected_interval_hours = interval_hours
            health.updated_at = now

            if error:
                health.status = "error"
                health.last_error_at = now
                health.last_error_message = str(error)[:500]
                health.error_count += 1
            else:
                health.status = "ok"
                health.last_success_at = now
                health.last_error_message = None
                health.records_processed = records

            if metadata:
                health.metadata_json = metadata

            session.add(health)
            await session.commit()

    except Exception as e:
        # Heartbeat failures should never crash the worker
        logger.debug(f"Heartbeat write failed for {pipeline_name}: {e}")


async def check_pipeline_health() -> list:
    """
    Check health of all pipelines. Returns list of status dicts.
    Used by the health API endpoint.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.exec(select(PipelineHealth).limit(50))
            pipelines = result.all()

            now = datetime.utcnow()
            statuses = []

            for p in pipelines:
                # Determine if pipeline is stale
                effective_status = p.status
                hours_since_run = None

                if p.last_run_at:
                    hours_since_run = (now - p.last_run_at).total_seconds() / 3600
                    # Stale if it hasn't run in 2x its expected interval
                    if hours_since_run > p.expected_interval_hours * 2:
                        effective_status = "stale"
                    elif hours_since_run > p.expected_interval_hours * 1.5:
                        effective_status = "warning"
                else:
                    effective_status = "never_run"

                statuses.append({
                    "pipeline": p.pipeline_name,
                    "status": effective_status,
                    "last_run": p.last_run_at.isoformat() if p.last_run_at else None,
                    "last_success": p.last_success_at.isoformat() if p.last_success_at else None,
                    "last_error": p.last_error_message,
                    "records_processed": p.records_processed,
                    "run_count": p.run_count,
                    "error_count": p.error_count,
                    "hours_since_run": round(hours_since_run, 1) if hours_since_run else None,
                    "expected_interval_hours": p.expected_interval_hours,
                    "duration_seconds": p.run_duration_seconds,
                })

            return statuses

    except Exception as e:
        logger.error(f"Pipeline health check failed: {e}")
        return []
