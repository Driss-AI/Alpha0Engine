"""
Run Tracker — wraps ingestion run lifecycle.

Usage:
    tracker = RunTracker("ingest-edgar")
    tracker.start()
    for item in items:
        try:
            process(item)
            tracker.record_success()
        except Exception as e:
            tracker.record_error(str(e))
    await tracker.finish()
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from shared.clients.postgres import AsyncSessionLocal
from shared.schemas.ingestion_run import IngestionRun

log = logging.getLogger(__name__)

MAX_ERROR_MESSAGES = 50  # cap stored error messages


class RunTracker:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.run = IngestionRun(service_name=service_name)
        self._error_msgs: list[str] = []

    def start(self):
        self.run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.run.status = "running"
        log.info(f"[{self.service_name}] Run started: {self.run.id}")

    def record_success(self, count: int = 1):
        self.run.records_processed += count

    def record_skip(self, count: int = 1):
        self.run.records_skipped += count

    def record_error(self, message: str):
        self.run.errors += 1
        if len(self._error_msgs) < MAX_ERROR_MESSAGES:
            self._error_msgs.append(message[:500])

    async def finish(self, metadata: Optional[dict] = None):
        self.run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.run.error_messages = self._error_msgs
        if self.run.errors > 0 and self.run.records_processed == 0:
            self.run.status = "error"
        elif self.run.errors > 0:
            self.run.status = "partial"
        else:
            self.run.status = "success"
        if metadata:
            self.run.run_metadata = metadata

        try:
            async with AsyncSessionLocal() as session:
                session.add(self.run)
                await session.commit()
            log.info(
                f"[{self.service_name}] Run complete: "
                f"processed={self.run.records_processed} "
                f"skipped={self.run.records_skipped} "
                f"errors={self.run.errors} "
                f"status={self.run.status}"
            )
        except Exception as e:
            log.error(f"[{self.service_name}] Failed to persist run record: {e}")

        # Sprint 6.4 — upsert data_freshness in a separate transaction so failures
        # here can't blow away the ingestion_runs commit above.
        try:
            await _upsert_freshness(
                source=self.service_name,
                run_status=self.run.status,
                records_added=self.run.records_processed,
                completed_at=self.run.completed_at,
            )
        except Exception as e:
            log.warning(f"[{self.service_name}] Failed to upsert data_freshness: {e}")


async def _upsert_freshness(
    *,
    source: str,
    run_status: str,
    records_added: int,
    completed_at: datetime,
) -> None:
    """Upsert one `data_freshness` row reflecting the just-finished run.

    Status mapping:
        success / partial → fresh, consecutive_failures reset to 0
        error             → failing, consecutive_failures += 1
    """
    from sqlalchemy import select
    from shared.schemas.data_freshness import DataFreshness

    is_success = run_status in ("success", "partial")
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(DataFreshness).where(DataFreshness.source == source)
        )).scalar_one_or_none()

        if existing is None:
            existing = DataFreshness(source=source)
            session.add(existing)

        existing.last_attempt = completed_at
        existing.records_added_last_run = records_added
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if is_success:
            existing.last_successful_run = completed_at
            existing.consecutive_failures = 0
            existing.status = "fresh"
        else:
            existing.consecutive_failures = (existing.consecutive_failures or 0) + 1
            existing.status = "failing"

        await session.commit()
